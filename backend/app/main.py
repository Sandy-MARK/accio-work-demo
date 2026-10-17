from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import bailian, config, crawl, ingest, meta, search, store, tables
from .chunk import STRATEGIES

app = FastAPI(title="Accio Work 知识库演示")
store.init()

MAX_SIZE = 20 * 1024 * 1024


@app.get("/api/meta")
def get_meta():
    return {
        "options": meta.OPTIONS,
        "spaces": meta.SPACES,
        "strategies": STRATEGIES,
        "roles": {k: v["label"] for k, v in meta.ROLES.items()},
        "table_fields": {k: [[key, label] for key, label, _ in v] for k, v in tables.FIELDS.items()},
        "crawl_modes": crawl.MODES,
        "models": {"embedding": config.EMBED_MODEL, "dimensions": config.EMBED_DIM, "rerank": config.RERANK_MODEL},
        "retrieval": {
            "recall_k": config.RECALL_K,
            "top_k": config.TOP_K,
            "threshold": config.RERANK_THRESHOLD,
            "rerank_timeout_s": config.RERANK_TIMEOUT,
            "qa_direct": config.QA_DIRECT,
            "qa_gap": config.QA_GAP,
            "qa_suggest": config.QA_SUGGEST,
        },
        "api_key_configured": bool(config.API_KEY),
    }


@app.get("/api/docs")
def list_docs():
    with store.conn() as c:
        rows = c.execute("SELECT * FROM docs ORDER BY created_at DESC").fetchall()
        counts = {}
        for sql in (
            "SELECT doc_version_id, COUNT(*) FROM chunks WHERE kind != 'parent' GROUP BY doc_version_id",
            "SELECT doc_version_id, COUNT(*) FROM table_rows GROUP BY doc_version_id",
            "SELECT doc_version_id, COUNT(*) FROM qa_units GROUP BY doc_version_id",
        ):
            counts[sql.split("FROM ")[1].split()[0]] = dict(c.execute(sql).fetchall())
    out = []
    for r in rows:
        d = ingest.summary(store.row(r))
        vid = d["doc_version_id"]
        d["chunk_count"] = counts["chunks"].get(vid, 0)
        d["row_count"] = counts["table_rows"].get(vid, 0)
        d["qa_count"] = counts["qa_units"].get(vid, 0)
        out.append(d)
    return out


@app.get("/api/docs/{version_id}")
def get_doc(version_id: str):
    with store.conn() as c:
        d = store.row(c.execute("SELECT * FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone())
        if not d:
            raise HTTPException(404, "文档不存在")
        chunks = [
            {k: v for k, v in store.row(r).items() if k != "embedding"} | {"embedded": r["embedding"] is not None}
            for r in c.execute("SELECT * FROM chunks WHERE doc_version_id = ? ORDER BY seq", (version_id,))
        ]
        rows = [store.row(r) for r in c.execute(
            "SELECT sheet, row_no, data FROM table_rows WHERE doc_version_id = ? ORDER BY sheet, row_no LIMIT 500",
            (version_id,),
        )]
        units = [
            {k: v for k, v in store.row(r).items() if k != "embeddings"} | {"embedded": r["embeddings"] is not None}
            for r in c.execute("SELECT * FROM qa_units WHERE doc_version_id = ? ORDER BY qa_id", (version_id,))
        ]
    if d["table_kind"]:
        for r in rows:
            r["row_status"] = tables.row_status(d["table_kind"], r["data"]["fields"]) \
                if d["table_kind"] in ("price", "freight") else "active"
    return ingest.summary(d) | {"parsed_md": d["parsed_md"], "chunks": chunks, "table_rows": rows, "qa_units": units}


def _run(fn, *args):
    try:
        return fn(*args)
    except bailian.BailianError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/docs/{version_id}")
def delete_doc(version_id: str):
    _run(ingest.delete, version_id)
    return {"ok": True}


@app.post("/api/docs")
async def upload(
    file: UploadFile = File(...),
    knowledge_space_id: str = Form(...),
    knowledge_type: str = Form(...),
    table_kind: str = Form(""),
    source_type: str = Form("user_upload"),
    platform: str = Form("general"),
    market: str = Form("unknown"),
    language: str = Form("zh"),
    business_domain: str = Form(...),
    access_level: str = Form(""),
    dept_ids: str = Form(""),
    quality_grade: str = Form("candidate"),
    risk_level: str = Form("normal"),
    effective_from: str = Form(""),
    expires_at: str = Form(""),
):
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "单个文件不能超过 20 MB")
    m = {k: v for k, v in locals().items() if k in ingest.FIELDS}
    return _run(ingest.ingest, file.filename or "未命名", data, m)


@app.post("/api/docs/{version_id}/reindex")
def reindex(version_id: str):
    _run(ingest.reembed, version_id)
    return {"ok": True}


class ReviewReq(BaseModel):
    action: str


@app.post("/api/docs/{version_id}/review")
def review(version_id: str, req: ReviewReq):
    if req.action not in ("approve", "reject"):
        raise HTTPException(400, "action 只能是 approve 或 reject")
    return _run(ingest.review, version_id, req.action)


class CrawlReq(BaseModel):
    url: str
    mode: str = "page"
    meta: dict


@app.get("/api/crawl")
def list_crawl():
    return crawl.list_sources()


@app.post("/api/crawl")
def create_crawl(req: CrawlReq):
    return _run(crawl.create, req.url.strip(), req.mode, req.meta)


@app.post("/api/crawl/{source_id}/run")
def run_crawl(source_id: str):
    return _run(crawl.run, source_id)


class SearchReq(BaseModel):
    query: str
    role: str = "zhangsan"
    platform: str | None = None
    market: str | None = None


@app.post("/api/search")
def do_search(req: SearchReq):
    if not req.query.strip():
        raise HTTPException(400, "请输入问题")
    if req.role not in meta.ROLES:
        raise HTTPException(400, "未知身份")
    return _run(search.search, req.query.strip(), req.role, req.platform or None, req.market or None)
