"""在线检索：权限与适用条件过滤 → 关键词 + 向量召回 → RRF 融合 30 条 → qwen3-rerank → 阈值 → Top-5 → 父块回填。"""
import math
import re
import time
from collections import Counter
from datetime import date

from . import bailian, config, store

ROLES = {
    "merchant": {"label": "商家自建 Agent（公开 + 本人私有）", "access": {"public", "private"}},
    "official": {"label": "Accio Work 官方 Agent（公开 + 内部 + 本人私有）", "access": {"public", "internal", "private"}},
}

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


def _candidates(role: str, platform: str | None, market: str | None) -> tuple[list[dict], dict]:
    today = date.today().isoformat()
    allowed = ROLES[role]["access"]
    with store.conn() as c:
        docs = [store.row(r) for r in c.execute("SELECT * FROM docs WHERE status = 'indexed'")]
        stats = {"total_docs": len(docs), "filtered_out": []}
        keep = {}
        for d in docs:
            reason = None
            if d["access_level"] not in allowed:
                reason = f"权限级别 {d['access_level']} 不在当前身份可见范围"
            elif (v := validity(d, today)) != "active":
                reason = f"效力状态 {v}"
            elif platform and d["platform"] not in (platform, "general"):
                reason = f"平台 {d['platform']} 与筛选 {platform} 不符"
            elif market and market not in d["market"].split(",") and d["market"] != "unknown":
                reason = f"市场 {d['market']} 不含 {market}"
            if reason:
                stats["filtered_out"].append({"name": d["name"], "version": d["version"], "reason": reason})
            else:
                keep[d["doc_version_id"]] = d
        if not keep:
            return [], stats
        marks = ",".join("?" * len(keep))
        rows = c.execute(
            f"SELECT * FROM chunks WHERE doc_version_id IN ({marks}) AND kind != 'parent' AND embedding IS NOT NULL",
            list(keep),
        )
        chunks = []
        for r in rows:
            ch = store.row(r)
            ch["doc"] = keep[ch["doc_version_id"]]
            chunks.append(ch)
    return chunks, stats


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


def search(query: str, role: str = "merchant", platform: str | None = None, market: str | None = None) -> dict:
    t0 = time.perf_counter()
    timing = {}
    chunks, stats = _candidates(role, platform, market)
    timing["过滤"] = round((time.perf_counter() - t0) * 1000)
    result = {"query": query, "role": ROLES[role]["label"], "filter": stats, "candidates": len(chunks)}
    if not chunks:
        return {**result, "status": "empty", "message": "当前身份与筛选条件下没有可检索的文档", "timing": timing}

    t = time.perf_counter()
    kw = _bm25(query, chunks)[: config.RECALL_K]
    timing["关键词召回"] = round((time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    qv = bailian.embed([query])[0]
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
        _brief(
            chunks[i],
            score=None if s is None else round(s, 3),
            parent=parents.get(chunks[i]["parent_chunk_id"]),
        )
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
    result["timing"] = timing
    result["threshold"] = config.RERANK_THRESHOLD
    return result
