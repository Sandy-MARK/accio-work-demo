"""阿里云百炼：text-embedding-v4 向量化与 qwen3-rerank 重排。"""
import httpx

from . import config


class BailianError(RuntimeError):
    pass


def _headers() -> dict:
    if not config.API_KEY:
        raise BailianError("未配置 DASHSCOPE_API_KEY，请在 backend/.env 中填写后重启后端")
    return {"Authorization": f"Bearer {config.API_KEY}", "Content-Type": "application/json"}


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code != 200:
        raise BailianError(f"{what}失败：HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), config.EMBED_BATCH):
        batch = texts[i : i + config.EMBED_BATCH]
        r = httpx.post(
            f"{config.BASE_URL}/compatible-mode/v1/embeddings",
            headers=_headers(),
            json={
                "model": config.EMBED_MODEL,
                "input": batch,
                "dimensions": config.EMBED_DIM,
                "encoding_format": "float",
            },
            timeout=60,
        )
        data = sorted(_check(r, "向量化")["data"], key=lambda d: d["index"])
        vectors += [d["embedding"] for d in data]
    return vectors


def rerank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """返回 [(原始下标, relevance_score)]，按分数从高到低。"""
    r = httpx.post(
        f"{config.BASE_URL}/api/v1/services/rerank/text-rerank/text-rerank",
        headers=_headers(),
        json={
            "model": config.RERANK_MODEL,
            "input": {"query": query, "documents": documents},
            "parameters": {"top_n": len(documents)},
        },
        timeout=config.RERANK_TIMEOUT,
    )
    results = _check(r, "重排")["output"]["results"]
    return [(x["index"], x["relevance_score"]) for x in results]
