"""在线检索：身份与适用条件过滤 → 标准问答匹配 → 结构化精确查询 →
关键词 + 向量召回 → RRF 融合 30 条 → qwen3-rerank → 阈值 → Top-5 → 父块回填。"""
import math
import re
import time
from collections import Counter
from datetime import date

from . import bailian, config, meta, qa, store, tables

_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9]+")


def tokens(text: str) -> list[str]:
    out = [w.lower() for w in _WORD.findall(text)]
    for run in _CJK_RUN.findall(text):
        out += list(run) if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)]
    return out


def validity(doc: dict, today: str) -> str:
    if doc["superseded"]:
        return "superseded"
    if doc["effective_from"] and doc["effective_from"] > today:
        return "pending"
    if doc["expires_at"] and doc["expires_at"] < today:
        return "repealed"
    return "active"


def _reason(d: dict, role: dict, platform: str | None, market: str | None, today: str) -> str | None:
    if d["review_status"] != "approved":
        return f"审核状态为「{meta.label('review_status', d['review_status'])}」，审核通过前不参与检索"
    if d["access_level"] not in role["access"]:
        return f"权限「{meta.label('access_level', d['access_level'])}」不在当前身份可见范围"
    if d["access_level"] == "department" and role["dept"] not in d["dept_ids"].split(","):
        depts = "、".join(meta.label("dept_ids", x) for x in d["dept_ids"].split(","))
        return f"仅{depts}可见"
    if role["exclude_pii"] and d["pii_level"] == "high":
        return "含个人信息，面向买家的身份不可见"
    if (v := validity(d, today)) != "active":
        return f"效力状态 {v}"
    if platform and d["platform"] not in (platform, "general"):
        return f"平台 {d['platform']} 与筛选 {platform} 不符"
    if market and market not in d["market"].split(",") and d["market"] != "unknown":
        return f"市场 {d['market']} 不含 {market}"
    return None


def _visible(role_key: str, platform: str | None, market: str | None) -> tuple[dict, dict]:
    today = date.today().isoformat()
    role = meta.ROLES[role_key]
    with store.conn() as c:
        docs = [store.row(r) for r in c.execute("SELECT * FROM docs WHERE status = 'indexed'")]
    stats = {"total_docs": len(docs), "filtered_out": []}
    keep = {}
    for d in docs:
        d.pop("parsed_md", None)
        if reason := _reason(d, role, platform, market, today):
            stats["filtered_out"].append({"name": d["name"], "version": d["version"], "reason": reason})
        else:
            keep[d["doc_version_id"]] = d
    return keep, stats


def _load(table: str, keep: dict, extra: str = "") -> list[dict]:
    if not keep:
        return []
    marks = ",".join("?" * len(keep))
    with store.conn() as c:
        rows = c.execute(f"SELECT * FROM {table} WHERE doc_version_id IN ({marks}) {extra}", list(keep)).fetchall()
    out = []
    for r in rows:
        x = store.row(r)
        x["doc"] = keep[x["doc_version_id"]]
        out.append(x)
    return out


def _structured(query: str, keep: dict) -> dict | None:
    tdocs = {k: d for k, d in keep.items() if d["knowledge_type"] == "data_table"}
    if not tdocs:
        return None
    skus = {s.upper() for s in tables.SKU_TOKEN.findall(query)}
    countries = [
        (code, name) for code, name in meta.OPTIONS["market"]
        if code != "unknown" and (name in query or re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", query))
    ]
    out = {"skus": sorted(skus), "countries": [n for _, n in countries], "hits": [], "excluded": []}
    if not skus and not countries:
        return out
    for r in _load("table_rows", tdocs):
        kind = r["doc"]["table_kind"]
        f = r["data"]["fields"]
        hit = f.get("sku_id", "").upper() in skus
        if kind == "freight" and countries:
            dest = f.get("destination", "").lower()
            hit = hit or any(code.lower() == dest or name in f.get("destination", "") for code, name in countries)
        if not hit:
            continue
        status = tables.row_status(kind, f) if kind in ("price", "freight") else "active"
        item = {
            "doc_name": r["doc"]["name"],
            "version": r["doc"]["version"],
            "table_kind": kind,
            "locator": f"{r['sheet']}；第 {r['row_no']} 行",
            "fields": [[tables.field_label(kind, k), v] for k, v in f.items()] + list(r["data"]["extra"].items()),
            "row_status": status,
        }
        (out["hits"] if status == "active" else out["excluded"]).append(item)
    out["hits"] = out["hits"][:20]
    return out


def _bm25(query: str, chunks: list[dict], k1=1.5, b=0.75) -> list[tuple[int, float]]:
    q = set(tokens(query))
    docs = [Counter(tokens(c["heading_path"] + " " + c["text"])) for c in chunks]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / max(n, 1)
    df = Counter(t for d in docs for t in q if t in d)
    scores = []
    for i, d in enumerate(docs):
        dl = sum(d.values())
        s = 0.0
        for t in q:
            if t not in d:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * dl / avg))
        if s > 0:
            scores.append((i, s))
    return sorted(scores, key=lambda x: -x[1])


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _brief(ch: dict, **extra) -> dict:
    return {
        "chunk_id": ch["chunk_id"],
        "doc_name": ch["doc"]["name"],
        "version": ch["doc"]["version"],
        "kind": ch["kind"],
        "locator": ch["locator"],
        "text": ch["text"],
        **extra,
    }


def search(query: str, role: str = "zhangsan", platform: str | None = None, market: str | None = None) -> dict:
    t0 = time.perf_counter()
    timing = {}
    keep, stats = _visible(role, platform, market)
    chunks = _load("chunks", keep, "AND kind != 'parent' AND embedding IS NOT NULL")
    units = _load("qa_units", keep, "AND embeddings IS NOT NULL")
    timing["过滤"] = round((time.perf_counter() - t0) * 1000)
    result = {
        "query": query,
        "role": meta.ROLES[role]["label"],
        "filter": stats,
        "candidates": len(chunks),
        "threshold": config.RERANK_THRESHOLD,
        "timing": timing,
    }

    t = time.perf_counter()
    result["structured"] = _structured(query, keep)
    timing["结构化查询"] = round((time.perf_counter() - t) * 1000)

    if not chunks and not units:
        return result | {"qa": None, "status": "empty", "message": "当前身份与筛选条件下没有可检索的文档"}

    t = time.perf_counter()
    qv = bailian.embed([query])[0]
    timing["问题向量化"] = round((time.perf_counter() - t) * 1000)

    result["qa"] = qa.match(qv, units) if units else None

    if not chunks:
        return result | {"status": "empty", "message": "没有可检索的文档块"}

    t = time.perf_counter()
    kw = _bm25(query, chunks)[: config.RECALL_K]
    timing["关键词召回"] = round((time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    vec = sorted(((i, _cos(qv, c["embedding"])) for i, c in enumerate(chunks)), key=lambda x: -x[1])[: config.RECALL_K]
    timing["向量召回"] = round((time.perf_counter() - t) * 1000)

    fused: dict[int, float] = {}
    for ranked in (kw, vec):
        for rank, (i, _) in enumerate(ranked, 1):
            fused[i] = fused.get(i, 0) + 1 / (config.RRF_K + rank)
    fused_list = sorted(fused.items(), key=lambda x: -x[1])[: config.RECALL_K]

    result["keyword"] = [_brief(chunks[i], score=round(s, 3)) for i, s in kw[:10]]
    result["vector"] = [_brief(chunks[i], score=round(s, 3)) for i, s in vec[:10]]
    result["fused"] = [_brief(chunks[i], score=round(s, 4)) for i, s in fused_list]

    t = time.perf_counter()
    docs = [(chunks[i]["heading_path"] + "\n" + chunks[i]["text"]).strip() for i, _ in fused_list]
    try:
        ranked = bailian.rerank(query, docs)
        reranked = [(fused_list[j][0], score) for j, score in ranked]
        result["rerank_status"] = "ok"
    except Exception as e:  # noqa: BLE001
        reranked = [(i, None) for i, _ in fused_list]
        result["rerank_status"] = "failed"
        result["rerank_error"] = str(e)
    timing["重排"] = round((time.perf_counter() - t) * 1000)

    result["reranked"] = [
        _brief(chunks[i], score=None if s is None else round(s, 3), passed=s is None or s >= config.RERANK_THRESHOLD)
        for i, s in reranked
    ]
    if result["rerank_status"] == "ok":
        final = [(i, s) for i, s in reranked if s >= config.RERANK_THRESHOLD][: config.TOP_K]
    else:
        final = reranked[: config.TOP_K]

    parent_ids = {chunks[i]["parent_chunk_id"] for i, _ in final if chunks[i]["parent_chunk_id"]}
    parents = {}
    if parent_ids:
        with store.conn() as c:
            marks = ",".join("?" * len(parent_ids))
            for r in c.execute(f"SELECT chunk_id, text, tokens FROM chunks WHERE chunk_id IN ({marks})", list(parent_ids)):
                parents[r["chunk_id"]] = {"text": r["text"], "tokens": r["tokens"]}

    result["final"] = [
        _brief(chunks[i], score=None if s is None else round(s, 3), parent=parents.get(chunks[i]["parent_chunk_id"]))
        for i, s in final
    ]
    if not final:
        result["status"] = "empty"
        result["message"] = f"重排后所有候选的相关分都低于 {config.RERANK_THRESHOLD}，视为知识库无依据，不用低分片段作答"
    elif result["rerank_status"] == "failed":
        result["status"] = "partial"
        result["message"] = "重排不可用，返回混合检索融合排序的前 5 条，标记为「未经重排」"
    else:
        result["status"] = "ok"
    return result
