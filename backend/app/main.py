import json
import re
import time
import uuid
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import bailian, config, search, store
from .chunk import STRATEGIES, chunk
from .parse import ParseError, parse

app = FastAPI(title="Accio Work 知识库演示")
store.init()

MAX_SIZE = 20 * 1024 * 1024

# 取值与 PRD 6.2 元数据字典一致；用列表保证前端下拉顺序
OPTIONS = {
    "knowledge_space_id": [
        ("kb_platform_rules", "平台规则库"),
        ("kb_help", "帮助中心"),
        ("kb_user_demo", "商家私有库（演示商家）"),
    ],
    "knowledge_type": [(k, v["label"]) for k, v in STRATEGIES.items()],
    "source_type": [
        ("official_rule", "平台官方规则"),
        ("help_doc", "官方帮助"),
        ("user_upload", "商家上传"),
        ("qa", "标准问答"),
        ("case", "案例"),
        ("web", "公开网页"),
    ],
    "platform": [
        ("general", "通用"),
        ("1688", "1688"),
        ("alibaba_com", "Alibaba.com"),
        ("amazon", "Amazon"),
        ("shopify", "Shopify"),
        ("tiktok_shop", "TikTok Shop"),
        ("unknown", "未知"),
    ],
    "market": [
        ("unknown", "未知"),
        ("US", "美国"),
        ("CN", "中国"),
        ("CA", "加拿大"),
        ("GB", "英国"),
        ("DE", "德国"),
        ("JP", "日本"),
    ],
    "language": [("zh", "中文"), ("en", "英语"), ("ja", "日语"), ("de", "德语"), ("fr", "法语"), ("es", "西班牙语")],
    "business_domain": [
        ("sourcing", "选品"),
        ("procurement", "采购比价"),
        ("listing", "发品"),
        ("store_analytics", "店铺分析"),
        ("ads", "广告"),
        ("sales", "销售跟进"),
        ("service", "客服售后"),
        ("logistics", "物流关税"),
        ("common", "通用"),
    ],
    "access_level": [("public", "公开"), ("internal", "内部"), ("private", "商家私有")],
    "quality_grade": [("gold", "黄金"), ("reviewed", "已审核"), ("candidate", "候选"), ("to_recheck", "待复核")],
    "risk_level": [("normal", "一般"), ("notice", "提示"), ("high", "高风险"), ("prohibited", "禁止")],
}
OPTION_KEYS = {f: {k for k, _ in v} for f, v in OPTIONS.items()}

SPACE_DEFAULT_ACCESS = {"kb_platform_rules": "public", "kb_help": "public", "kb_user_demo": "private"}
ACCESS_STRICTNESS = {"public": 0, "internal": 1, "private": 2}


@app.get("/api/meta")
def meta():
    return {
        "options": OPTIONS,
        "space_default_access": SPACE_DEFAULT_ACCESS,
        "strategies": STRATEGIES,
        "roles": {k: v["label"] for k, v in search.ROLES.items()},
        "models": {"embedding": config.EMBED_MODEL, "dimensions": config.EMBED_DIM, "rerank": config.RERANK_MODEL},
        "retrieval": {
            "recall_k": config.RECALL_K,
            "top_k": config.TOP_K,
            "threshold": config.RERANK_THRESHOLD,
            "rerank_timeout_s": config.RERANK_TIMEOUT,
        },
        "api_key_configured": bool(config.API_KEY),
    }


def _doc_summary(d: dict) -> dict:
    d = {k: v for k, v in d.items() if k != "parsed_md"}
    d["validity_status"] = search.validity(d, datetime.now().date().isoformat())
    return d


@app.get("/api/docs")
def list_docs():
    with store.conn() as c:
        rows = c.execute("SELECT * FROM docs ORDER BY created_at DESC").fetchall()
        counts = dict(
            c.execute("SELECT doc_version_id, COUNT(*) FROM chunks WHERE kind != 'parent' GROUP BY doc_version_id").fetchall()
        )
    out = []
    for r in rows:
        d = _doc_summary(store.row(r))
        d["chunk_count"] = counts.get(d["doc_version_id"], 0)
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
    d = _doc_summary(d) | {"parsed_md": d["parsed_md"], "chunks": chunks}
    return d


@app.delete("/api/docs/{version_id}")
def delete_doc(version_id: str):
    with store.conn() as c:
        d = c.execute("SELECT doc_id, version FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone()
        if not d:
            raise HTTPException(404, "文档不存在")
        c.execute("DELETE FROM chunks WHERE doc_version_id = ?", (version_id,))
        c.execute("DELETE FROM docs WHERE doc_version_id = ?", (version_id,))
        latest = c.execute(
            "SELECT doc_version_id FROM docs WHERE doc_id = ? ORDER BY version DESC LIMIT 1", (d["doc_id"],)
        ).fetchone()
        if latest:
            c.execute("UPDATE docs SET superseded = 0 WHERE doc_version_id = ?", (latest[0],))
    return {"ok": True}


def _check_option(field: str, value: str):
    if value not in OPTION_KEYS[field]:
        raise HTTPException(400, f"{field} 取值无效：{value}")


_SENSITIVE = [
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("银行卡号", re.compile(r"(?<!\d)(?:62|4\d|5[1-5])\d{14,17}(?!\d)")),
]


def _sensitive(text: str) -> list[str]:
    return [name for name, pat in _SENSITIVE if pat.search(text)]


@app.post("/api/docs")
async def upload(
    file: UploadFile = File(...),
    knowledge_space_id: str = Form(...),
    knowledge_type: str = Form(...),
    source_type: str = Form("user_upload"),
    platform: str = Form("general"),
    market: str = Form("unknown"),
    language: str = Form("zh"),
    business_domain: str = Form(...),
    access_level: str = Form(""),
    quality_grade: str = Form("candidate"),
    risk_level: str = Form("normal"),
    effective_from: str = Form(""),
    expires_at: str = Form(""),
):
    _check_option("knowledge_space_id", knowledge_space_id)
    default_access = SPACE_DEFAULT_ACCESS[knowledge_space_id]
    access_level = access_level or default_access
    for f, v in [
        ("knowledge_type", knowledge_type),
        ("source_type", source_type),
        ("platform", platform),
        ("language", language),
        ("access_level", access_level),
        ("quality_grade", quality_grade),
        ("risk_level", risk_level),
    ]:
        _check_option(f, v)
    for m in market.split(","):
        _check_option("market", m)
    for b in business_domain.split(","):
        _check_option("business_domain", b)
    if ACCESS_STRICTNESS[access_level] < ACCESS_STRICTNESS[default_access]:
        raise HTTPException(400, f"权限级别只能比知识空间默认值（{default_access}）更严，不能放宽")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "单个文件不能超过 20 MB")
    name = file.filename or "未命名"

    with store.conn() as c:
        prev = c.execute(
            "SELECT doc_id, MAX(version) FROM docs WHERE name = ? AND knowledge_space_id = ?",
            (name, knowledge_space_id),
        ).fetchone()
    doc_id = prev[0] or f"doc_{uuid.uuid4().hex[:10]}"
    version = (prev[1] or 0) + 1
    version_id = f"{doc_id}_v{version}"
    (config.RAW_DIR / f"{version_id}_{name}").write_bytes(data)

    steps: list[dict] = []
    record = {
        "doc_version_id": version_id,
        "doc_id": doc_id,
        "version": version,
        "name": name,
        "size": len(data),
        "knowledge_space_id": knowledge_space_id,
        "knowledge_type": knowledge_type,
        "source_type": source_type,
        "platform": platform,
        "market": market,
        "language": language,
        "business_domain": business_domain,
        "access_level": access_level,
        "quality_grade": quality_grade,
        "risk_level": risk_level,
        "processing_policy": "approved_cloud",
        "effective_from": effective_from or None,
        "expires_at": expires_at or None,
        "superseded": 0,
        "status": "processing",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    def save(status: str, error: str | None = None, parsed_md: str | None = None):
        record.update(status=status, error=error, steps=json.dumps(steps, ensure_ascii=False), parsed_md=parsed_md)
        with store.conn() as c:
            cols = ",".join(record)
            c.execute(
                f"INSERT OR REPLACE INTO docs ({cols}) VALUES ({','.join('?' * len(record))})", list(record.values())
            )

    def step(name: str, fn):
        t = time.perf_counter()
        try:
            out, detail = fn()
        except (ParseError, ValueError, bailian.BailianError) as e:
            steps.append({"name": name, "ok": False, "detail": str(e), "ms": round((time.perf_counter() - t) * 1000)})
            raise
        steps.append({"name": name, "ok": True, "detail": detail, "ms": round((time.perf_counter() - t) * 1000)})
        return out

    parsed = None
    try:
        parsed = step("解析", lambda: (lambda md: (md, f"转为 Markdown，共 {len(md)} 字符"))(parse(name, data)))
        chunks = step(
            "切块",
            lambda: (lambda cs: (cs, _chunk_detail(cs, knowledge_type)))(chunk(parsed, knowledge_type)),
        )
        if not chunks:
            raise ValueError("切块结果为空")
    except (ParseError, ValueError) as e:
        save("failed", str(e), parsed)
        return _doc_summary(record | {"steps": steps}) | {"chunk_count": 0}

    to_embed = [c for c in chunks if c.kind != "parent"]
    if found := _sensitive(parsed):
        record["processing_policy"] = "local_only"
        msg = f"检测到{'、'.join(found)}，处理位置策略为 local_only，不发往云端向量化；需在用户设备上用本地模型处理"
        steps.append({"name": "向量化", "ok": False, "detail": msg, "ms": 0})
        _write_chunks(version_id, chunks, None)
        save("failed", msg, parsed)
        return _doc_summary(record | {"steps": steps}) | {"chunk_count": len(to_embed)}

    vectors = None
    try:
        vectors = step(
            "向量化",
            lambda: (
                bailian.embed([(c.heading_path + "\n" + c.text).strip() for c in to_embed]),
                f"{config.EMBED_MODEL}，{len(to_embed)} 个块，{config.EMBED_DIM} 维",
            ),
        )
    except bailian.BailianError as e:
        _write_chunks(version_id, chunks, None)
        save("failed", str(e), parsed)
        return _doc_summary(record | {"steps": steps}) | {"chunk_count": len(to_embed)}

    def write_index():
        _write_chunks(version_id, chunks, vectors)
        if version > 1:
            with store.conn() as c:
                c.execute("UPDATE docs SET superseded = 1 WHERE doc_id = ? AND version < ?", (doc_id, version))
        note = f"；旧版本 v{version - 1} 标记为已被替代" if version > 1 else ""
        return None, f"写入 {len(chunks)} 条记录，可参与检索{note}"

    step("建索引", write_index)
    save("indexed", None, parsed)
    return _doc_summary(record | {"steps": steps}) | {"chunk_count": len(to_embed)}


@app.post("/api/docs/{version_id}/reindex")
def reindex(version_id: str):
    with store.conn() as c:
        d = store.row(c.execute("SELECT * FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone())
        if not d:
            raise HTTPException(404, "文档不存在")
        if d["processing_policy"] == "local_only":
            raise HTTPException(400, "该文档处理位置策略为 local_only，不能发往云端向量化")
        rows = c.execute(
            "SELECT chunk_id, heading_path, text FROM chunks WHERE doc_version_id = ? AND kind != 'parent' ORDER BY seq",
            (version_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(400, "该文档没有可向量化的块，请重新上传")
    steps = [s for s in d["steps"] if s["name"] in ("解析", "切块")]
    t = time.perf_counter()
    try:
        vectors = bailian.embed([(r["heading_path"] + "\n" + r["text"]).strip() for r in rows])
    except bailian.BailianError as e:
        steps.append({"name": "向量化", "ok": False, "detail": str(e), "ms": round((time.perf_counter() - t) * 1000)})
        with store.conn() as c:
            c.execute(
                "UPDATE docs SET status='failed', error=?, steps=? WHERE doc_version_id=?",
                (str(e), json.dumps(steps, ensure_ascii=False), version_id),
            )
        raise HTTPException(502, str(e))
    steps.append(
        {
            "name": "向量化",
            "ok": True,
            "detail": f"{config.EMBED_MODEL}，{len(rows)} 个块，{config.EMBED_DIM} 维",
            "ms": round((time.perf_counter() - t) * 1000),
        }
    )
    with store.conn() as c:
        for r, v in zip(rows, vectors):
            c.execute("UPDATE chunks SET embedding = ? WHERE chunk_id = ?", (json.dumps(v), r["chunk_id"]))
        if d["version"] > 1:
            c.execute("UPDATE docs SET superseded = 1 WHERE doc_id = ? AND version < ?", (d["doc_id"], d["version"]))
        steps.append({"name": "建索引", "ok": True, "detail": f"更新 {len(rows)} 个块的向量，可参与检索", "ms": 0})
        c.execute(
            "UPDATE docs SET status='indexed', error=NULL, steps=? WHERE doc_version_id=?",
            (json.dumps(steps, ensure_ascii=False), version_id),
        )
    return {"ok": True}


def _write_chunks(version_id: str, chunks, vectors):
    ids = [f"{version_id}_c{i:04d}" for i in range(len(chunks))]
    vec_iter = iter(vectors or [])
    with store.conn() as c:
        for i, ch in enumerate(chunks):
            emb = None if ch.kind == "parent" or vectors is None else json.dumps(next(vec_iter))
            c.execute(
                "INSERT INTO chunks (chunk_id, doc_version_id, parent_chunk_id, kind, seq, text, tokens,"
                " heading_path, locator, embedding) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ids[i],
                    version_id,
                    ids[ch.parent] if ch.parent is not None else None,
                    ch.kind,
                    i,
                    ch.text,
                    ch.tokens,
                    ch.heading_path,
                    ch.locator,
                    emb,
                ),
            )


def _chunk_detail(cs, kt: str) -> str:
    s = STRATEGIES[kt]
    leaf = [c for c in cs if c.kind != "parent"]
    parents = len(cs) - len(leaf)
    sizes = [c.tokens for c in leaf] or [0]
    pc = f"，父块 {parents} 个" if parents else ""
    return f"{s['strategy']}（{s['size']}）：检索块 {len(leaf)} 个{pc}，长度 {min(sizes)}–{max(sizes)}"


class SearchReq(BaseModel):
    query: str
    role: str = "merchant"
    platform: str | None = None
    market: str | None = None


@app.post("/api/search")
def do_search(req: SearchReq):
    if not req.query.strip():
        raise HTTPException(400, "请输入问题")
    if req.role not in search.ROLES:
        raise HTTPException(400, "未知身份")
    try:
        return search.search(req.query.strip(), req.role, req.platform or None, req.market or None)
    except bailian.BailianError as e:
        raise HTTPException(502, str(e))
