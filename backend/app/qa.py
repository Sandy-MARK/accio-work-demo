"""标准问答库：从文档抽取「标准问 + 相似问 + 答案」，检索时先于 RAG 匹配。"""
import math
import re

from . import config
from .chunk import sections

_LEAD = r"^\s*(?:\*\*)?\s*"
_TAIL = r"\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$"
_Q = re.compile(_LEAD + r"(?:Q\d*|问|问题|标准问)" + _TAIL)
_SIM = re.compile(_LEAD + r"(?:相似问|相似问题|同义问)" + _TAIL)
_A = re.compile(_LEAD + r"(?:A\d*|答|答案|回答)" + _TAIL)
_SPLIT_SIM = re.compile(r"[；;|｜]")


def _clean(s: str) -> str:
    return s.strip().strip("*").strip()


def _sims(s: str) -> list[str]:
    return [x for x in (_clean(p) for p in _SPLIT_SIM.split(s)) if x]


def _from_lines(lines: list[str], locator: str) -> list[dict]:
    units: list[dict] = []
    cur: dict | None = None
    in_answer = False
    for ln in lines:
        if m := _Q.match(ln):
            cur = {"standard_question": _clean(m.group(1)), "similar_questions": [], "answer": "", "locator": locator}
            units.append(cur)
            in_answer = False
        elif cur is None:
            continue
        elif m := _SIM.match(ln):
            cur["similar_questions"] += _sims(m.group(1))
        elif m := _A.match(ln):
            cur["answer"] = _clean(m.group(1))
            in_answer = True
        elif in_answer and ln.strip():
            cur["answer"] += "\n" + ln.strip()
    return units


def _from_table(lines: list[str], locator: str) -> list[dict]:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines if ln.lstrip().startswith("|")]
    rows = [r for r in rows if not all(re.fullmatch(r":?-+:?", c or "-") for c in r)]
    if len(rows) < 2:
        return []
    head = rows[0]

    def col(*names):
        return next((i for i, h in enumerate(head) if any(n in h for n in names)), None)

    qi, si, ai = col("标准问", "问题"), col("相似问", "同义问"), col("答案", "回答")
    if qi is None or ai is None:
        return []
    units = []
    for n, r in enumerate(rows[1:], 2):
        r = r + [""] * (len(head) - len(r))
        if r[qi] and r[ai]:
            units.append(
                {
                    "standard_question": r[qi],
                    "similar_questions": _sims(r[si]) if si is not None else [],
                    "answer": r[ai],
                    "locator": f"{locator}；第 {n} 行" if locator else f"第 {n} 行",
                }
            )
    return units


def extract(md: str) -> list[dict]:
    units = []
    for s in sections(md):
        loc = " > ".join(s.path)
        lines = s.text.splitlines()
        units += _from_table(lines, loc) or _from_lines(lines, loc)
    return [u for u in units if u["standard_question"] and u["answer"]]


def variants(u: dict) -> list[str]:
    return [u["standard_question"], *u["similar_questions"]]


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def match(qv: list[float], units: list[dict]) -> dict:
    """按问题向量与每条标准问/相似问的最高相似度判定走向。"""
    scored = []
    for u in units:
        vs = variants(u)
        best = max(range(len(vs)), key=lambda i: _cos(qv, u["embeddings"][i]))
        scored.append((_cos(qv, u["embeddings"][best]), vs[best], u))
    scored.sort(key=lambda x: -x[0])

    def brief(s, q, u):
        return {
            "qa_id": u["qa_id"],
            "standard_question": u["standard_question"],
            "matched_question": q,
            "score": round(s, 3),
            "answer": u["answer"],
            "doc_name": u["doc"]["name"],
            "version": u["doc"]["version"],
            "locator": u["locator"],
        }

    cands = [brief(*x) for x in scored[: config.QA_TOP_K]]
    high = [c for c in cands if c["score"] >= config.QA_DIRECT]
    out = {
        "candidates": cands,
        "unit_count": len(units),
        "thresholds": {"direct": config.QA_DIRECT, "gap": config.QA_GAP, "suggest": config.QA_SUGGEST},
    }
    if len(high) == 1 or (len(high) >= 2 and high[0]["score"] - high[1]["score"] >= config.QA_GAP):
        reason = "仅 1 条达到直答线" if len(high) == 1 else f"第一名领先第二名 {high[0]['score'] - high[1]['score']:.3f}"
        return out | {"decision": "direct", "hit": high[0], "message": f"命中标准问答，{reason}，直接用标准答案作答"}
    if len(high) >= 2:
        return out | {
            "decision": "choose",
            "options": high,
            "message": f"{len(high)} 条都达到直答线且差距小于 {config.QA_GAP}，请用户选择要问的是哪一个",
        }
    near = [c for c in cands if c["score"] >= config.QA_SUGGEST]
    if near:
        return out | {
            "decision": "suggest",
            "options": near,
            "message": "没有达到直答线的问答，给出「你是不是想问」候选，同时用 RAG 检索作答",
        }
    return out | {"decision": "rag", "message": f"最高相似度低于 {config.QA_SUGGEST}，交给 RAG 检索"}
