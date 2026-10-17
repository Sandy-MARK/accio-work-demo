"""前台问答：按检索结果决定直答、请用户选择、依据作答或无依据回复。"""
import re
from datetime import date

from . import bailian, config, search

TABLE_KINDS = {"catalog": "商品目录", "price": "价格表", "freight": "运价表", "cost": "成本表"}
BUYER_FACING = {"reception"}
NO_BASIS = "知识库中没有找到相关依据"
SYSTEM = f"""你是 Accio Work 的知识助手，只依据下方编号资料回答用户问题。

规则：
1. 不使用资料以外的知识，不编造数字、规则或链接。
2. 第一句直接给结论；然后用列表或表格写细节；最后一句给下一步建议。
3. 用到资料的句子末尾标注来源，写法固定为 [A]、[B]，字母取资料前【资料 X】的 X；只标实际用到的。正文不要写「资料 A」这类字样。
4. 资料只覆盖问题的一部分时，先回答能回答的部分，再说明哪些没有找到依据。问题问的概念在资料里没有直接对应时（例如问成本、资料只有售价），第一句先说明没有找到该项，再列出资料里相近的信息并写明它是什么，不要把相近信息当成答案。
5. 资料与问题无关时，只回复：{NO_BASIS}。
6. 问到个人积分余额、账单、消耗明细等个人数据时，说明无法查询，引导到「帮助中心 → 客服」。
7. 价格、运费类回答注明币种、适用数量段和生效日期；按今天的日期判断是否已生效，不做假设。
8. 只列出资料中的原始数值。禁止出现任何算式、换算、估算或合计（例如「62 × 0.12」「约 7.44 元」「总价约」）；用户需要测算时，建议使用报价工具。不要编造资料中没有的入口、菜单或页面路径。
9. 运费按目的国查询；问到运费但问题和资料里都没有目的国时，请用户补充目的国，不要回答没有依据。
10. 与用户使用同一种语言，使用 Markdown。"""

FORMULA = re.compile(r"\d\s*[×*÷]\s*\d|[=＝]\s*\**\s*\d")
REWRITE = "上一版回答出现了算式或推算结果，违反规则 8。请删掉所有算式、换算和推算结果，只保留资料中的原始数值后重写。"
FORMULA_FALLBACK = (
    "这个问题需要在资料数值的基础上做测算，我只提供原始数据，不替你计算，以免出错。\n\n"
    "- 相关的原始数据见下方来源；\n"
    "- 需要测算总价或运费时，请使用报价工具。"
)

NOT_FOUND = (
    "我在当前可访问的知识库（帮助中心、平台规则库、团队知识库、个人知识库）中没有找到能回答这个问题的依据，"
    "就不凭常识作答了。\n\n"
    "- 换个说法，或补充平台、市场、商品型号再问一次；\n"
    "- 需要人工协助时，点击左上角「帮助中心」联系客服。"
)


def _label(n: int) -> str:
    return chr(ord("A") + n - 1)


def _row_text(hit: dict) -> str:
    fields = "；".join(f"{k} {v}" for k, v in hit["fields"] if v not in ("", None))
    return f"（{TABLE_KINDS.get(hit['table_kind'], hit['table_kind'])}）{fields}"


def _trace(r: dict, role: str) -> dict:
    qa = r.get("qa") or {}
    st = r.get("structured") or {}
    filtered = r["filter"]["filtered_out"]
    return {
        "role": r["role"],
        "filtered_count": len(filtered),
        "filtered": [] if role in BUYER_FACING else filtered,
        "qa": {"decision": qa.get("decision"), "message": qa.get("message"),
               "top": [[c["standard_question"], c["score"]] for c in qa.get("candidates", [])]},
        "structured": {"hits": len(st.get("hits", [])), "excluded": len(st.get("excluded", []))},
        "rag": {"status": r.get("status"), "message": r.get("message"),
                "kept": len(r.get("final", [])), "threshold": r["threshold"],
                "rerank_status": r.get("rerank_status")},
        "timing": r["timing"],
    }


def answer(query: str, role: str, history: list[dict]) -> dict:
    r = search.search(query, role)
    trace = _trace(r, role)
    qa = r.get("qa") or {}
    decision = qa.get("decision")

    if decision == "direct":
        hit = qa["hit"]
        return {
            "mode": "qa",
            "answer": hit["answer"],
            "sources": [{"n": 1, "doc_name": hit["doc_name"], "version": hit["version"],
                         "locator": hit["locator"], "kind": "标准问答", "score": hit["score"]}],
            "trace": trace,
        }
    if decision == "choose":
        return {
            "mode": "choose",
            "answer": "有几条标准问题都和你的问题很接近，你想问的是哪一个？",
            "options": [o["standard_question"] for o in qa["options"]],
            "trace": trace,
        }

    suggestions = [o["standard_question"] for o in qa.get("options", [])] if decision == "suggest" else []
    evidence, sources = [], []
    for hit in (r.get("structured") or {}).get("hits", [])[:10]:
        n = len(sources) + 1
        evidence.append(f"【资料 {_label(n)}】{hit['doc_name']}（{hit['locator']}）{_row_text(hit)}")
        sources.append({"n": n, "doc_name": hit["doc_name"], "version": hit["version"],
                        "locator": hit["locator"], "kind": "表格行"})
    for ch in r.get("final", []):
        n = len(sources) + 1
        body = (ch.get("parent") or {}).get("text") or ch["text"]
        evidence.append(f"【资料 {_label(n)}】{ch['doc_name']}（{ch['locator']}）\n{body}")
        sources.append({"n": n, "doc_name": ch["doc_name"], "version": ch["version"],
                        "locator": ch["locator"], "kind": "文档片段", "score": ch.get("score")})

    if not evidence:
        return {"mode": "empty", "answer": NOT_FOUND, "suggestions": suggestions, "sources": [], "trace": trace}

    excluded = len((r.get("structured") or {}).get("excluded", []))
    note = f"\n\n（另有 {excluded} 行价格或运价已过期或未生效，已排除，不得使用。）" if excluded else ""
    messages = [{"role": "system", "content": SYSTEM}]
    messages += history[-config.CHAT_HISTORY:]
    messages.append({
        "role": "user",
        "content": f"今天是 {date.today().isoformat()}。\n\n资料：\n\n" + "\n\n".join(evidence) + note + f"\n\n问题：{query}",
    })
    raw = bailian.chat(messages)
    if FORMULA.search(raw):
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": REWRITE}]
        raw = bailian.chat(messages)
        if FORMULA.search(raw):
            raw = FORMULA_FALLBACK
    labels = {_label(s["n"]): s["n"] for s in sources}
    text = re.sub(
        r"\[([A-Z])\]",
        lambda m: f"[{labels[m.group(1)]}]" if m.group(1) in labels else "",
        raw,
    )
    if text.startswith(NO_BASIS):
        return {"mode": "empty", "answer": NOT_FOUND, "suggestions": suggestions, "sources": [], "trace": trace}
    return {
        "mode": "rag",
        "answer": text,
        "sources": sources,
        "suggestions": suggestions,
        "unreranked": r.get("rerank_status") == "failed",
        "trace": trace,
    }
