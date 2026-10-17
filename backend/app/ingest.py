"""入库流水线：解析 → 切块 / 结构化抽取 / 问答抽取 → 敏感信息检查 → 向量化 → 建索引。上传与网页抓取共用。"""
import hashlib
import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

from . import bailian, config, meta, qa, store, tables
from .chunk import STRATEGIES, Chunk, chunk
from .parse import ParseError, parse, read_rows


class IngestError(ValueError):
    pass


class Duplicate(IngestError):
    def __init__(self, msg: str, existing: dict):
        super().__init__(msg)
        self.existing = existing


FIELDS = [
    "knowledge_space_id",
    "knowledge_type",
    "table_kind",
    "source_type",
    "platform",
    "market",
    "language",
    "business_domain",
    "access_level",
    "dept_ids",
    "quality_grade",
    "risk_level",
    "effective_from",
    "expires_at",
]
_MULTI = {"market", "business_domain", "dept_ids"}


def validate(m: dict) -> dict:
    m = {k: (m.get(k) or "").strip() for k in FIELDS}
    space = m["knowledge_space_id"]
    if space not in meta.SPACES:
        raise IngestError(f"knowledge_space_id 取值无效：{space}")
    allowed = meta.SPACES[space]["access"]
    m["access_level"] = m["access_level"] or allowed[0]
    if m["access_level"] not in allowed:
        names = "、".join(meta.label("access_level", a) for a in allowed)
        raise IngestError(f"{meta.label('knowledge_space_id', space)}只允许以下权限：{names}")
    if m["access_level"] == "department":
        if not m["dept_ids"]:
            raise IngestError("权限为「指定部门」时必须选择至少一个部门")
    else:
        m["dept_ids"] = ""
    if m["knowledge_type"] == "data_table":
        if not m["table_kind"]:
            raise IngestError("数据表格必须选择表格类别")
    else:
        m["table_kind"] = ""
    defaults = {"source_type": "user_upload", "platform": "general", "market": "unknown", "language": "zh",
                "quality_grade": "candidate", "risk_level": "normal"}
    for k, v in defaults.items():
        m[k] = m[k] or v
    if not m["business_domain"]:
        raise IngestError("请选择业务域")
    for k, v in m.items():
        if k in ("effective_from", "expires_at") or not v:
            continue
        for x in v.split(",") if k in _MULTI else [v]:
            if x not in meta.OPTION_KEYS[k]:
                raise IngestError(f"{k} 取值无效：{x}")
    return m


_PII = [
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), True),
    ("银行卡号", re.compile(r"(?<!\d)(?:62|4\d|5[1-5])\d{14,17}(?!\d)"), True),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), False),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"), False),
]


def detect_pii(text: str, space: str) -> tuple[list[str], bool]:
    """返回 (命中的类别, 是否必须本地处理)。平台公共知识中的联系方式属于公开信息，不计个人信息。"""
    public = meta.SPACES[space]["review"]
    found, local = [], False
    for name, pat, must_local in _PII:
        if (must_local or not public) and pat.search(text):
            found.append(name)
            local = local or must_local
    return found, local


@contextmanager
def _step(steps: list, name: str):
    t = time.perf_counter()
    s = {"name": name, "ok": True, "detail": "", "ms": 0}
    try:
        yield s
    except Exception as e:
        s.update(ok=False, detail=str(e))
        raise
    finally:
        s["ms"] = round((time.perf_counter() - t) * 1000)
        steps.append(s)


def summary(d: dict) -> dict:
    from .search import validity

    d = {k: v for k, v in d.items() if k != "parsed_md"}
    d["validity_status"] = validity(d, datetime.now().date().isoformat())
    return d


def ingest(name: str, data: bytes, m: dict, source_url: str = "", parse_name: str | None = None) -> dict:
    m = validate(m)
    space, kt = m["knowledge_space_id"], m["knowledge_type"]
    parse_name = parse_name or name
    steps: list[dict] = []

    records: list[dict] = []
    with _step(steps, "解析") as s:
        md = parse(parse_name, data)
        s["detail"] = f"转为 Markdown，共 {len(md)} 字符"
    if kt == "data_table":
        with _step(steps, "结构化抽取") as s:
            records, note = tables.extract(m["table_kind"], read_rows(parse_name, data))
            s["detail"] = note

    content_hash = hashlib.sha256(md.encode()).hexdigest()
    key_col, key_val = ("source_url", source_url) if source_url else ("name", name)
    with store.conn() as c:
        dup = c.execute(
            "SELECT doc_version_id, name, version FROM docs WHERE knowledge_space_id = ? AND content_hash = ?"
            " AND superseded = 0 AND status != 'failed'",
            (space, content_hash),
        ).fetchone()
        if dup:
            raise Duplicate(f"与已入库的《{dup['name']}》v{dup['version']} 内容完全相同，未重复入库", dict(dup))
        prev = c.execute(
            f"SELECT doc_id, MAX(version) FROM docs WHERE {key_col} = ? AND knowledge_space_id = ?", (key_val, space)
        ).fetchone()
    doc_id = prev[0] or f"doc_{uuid.uuid4().hex[:10]}"
    version = (prev[1] or 0) + 1
    version_id = f"{doc_id}_v{version}"
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", name)[:80]
    (config.RAW_DIR / f"{version_id}_{safe}").write_bytes(data)

    needs_review = meta.SPACES[space]["review"]
    record = m | {
        "doc_version_id": version_id,
        "doc_id": doc_id,
        "version": version,
        "name": name,
        "size": len(data),
        "effective_from": m["effective_from"] or None,
        "expires_at": m["expires_at"] or None,
        "processing_policy": "approved_cloud",
        "review_status": "unreviewed" if needs_review else "approved",
        "pii_level": "none",
        "content_hash": content_hash,
        "source_url": source_url,
        "superseded": 0,
        "status": "processing",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parsed_md": md,
    }

    def save(status: str, error: str | None = None):
        record.update(status=status, error=error, steps=json.dumps(steps, ensure_ascii=False))
        with store.conn() as c:
            c.execute(
                f"INSERT OR REPLACE INTO docs ({','.join(record)}) VALUES ({','.join('?' * len(record))})",
                list(record.values()),
            )

    def result(status_note: int):
        return summary(record | {"steps": steps}) | {"chunk_count": status_note}

    units: list[dict] = []
    try:
        with _step(steps, "切块") as s:
            if kt == "data_table":
                if m["table_kind"] == "catalog":
                    chunks = [
                        Chunk("normal", tables.sku_text(r), r["sheet"], None, rows=f"第 {r['row_no']} 行")
                        for r in records
                    ]
                    s["detail"] = f"每个 SKU 生成 1 条描述块，共 {len(chunks)} 个，用于语义检索"
                else:
                    chunks = []
                    s["detail"] = "价格、运价、成本类表格不切块、不向量化，只走结构化精确查询"
            else:
                chunks = chunk(md, kt)
                if not chunks:
                    raise ValueError("切块结果为空")
                s["detail"] = _chunk_detail(chunks, kt)
        if kt == "qa":
            with _step(steps, "问答抽取") as s:
                units = qa.extract(md)
                sims = sum(len(u["similar_questions"]) for u in units)
                s["detail"] = (
                    f"{len(units)} 条标准问，{sims} 条相似问，写入标准问答库"
                    if units
                    else "未识别到「Q：/相似问：/A：」或「标准问/相似问/答案」表格格式，只按普通块入库"
                )
    except (ParseError, ValueError) as e:
        save("failed", str(e))
        return result(0)

    leaf = [c for c in chunks if c.kind != "parent"]
    with _step(steps, "敏感信息检查") as s:
        found, local = detect_pii(md, space)
        if found:
            record["pii_level"] = "high"
        if local:
            record["processing_policy"] = "local_only"
        s["detail"] = (
            f"检测到{'、'.join(found)}，个人信息等级记为高；"
            + ("处理位置策略为 local_only，不发往云端向量化" if local else "可云端处理，面向买家的接待场景不可见")
            if found
            else "未发现个人信息"
        )
    if local:
        _write(version_id, chunks, None, records, units, None)
        save("failed", "含身份证号或银行卡号，需在用户设备上用本地模型处理")
        return result(len(leaf))

    texts = [(c.heading_path + "\n" + c.text).strip() for c in leaf]
    qa_texts = [v for u in units for v in qa.variants(u)]
    vectors = qa_vectors = None
    if texts or qa_texts:
        try:
            with _step(steps, "向量化") as s:
                allv = bailian.embed(texts + qa_texts)
                vectors, qa_vectors = allv[: len(texts)], allv[len(texts) :]
                s["detail"] = f"{config.EMBED_MODEL}，{len(texts)} 个块" + (
                    f" + {len(qa_texts)} 条问法" if qa_texts else ""
                ) + f"，{config.EMBED_DIM} 维"
        except bailian.BailianError as e:
            _write(version_id, chunks, None, records, units, None)
            save("failed", str(e))
            return result(len(leaf))

    with _step(steps, "建索引") as s:
        _write(version_id, chunks, vectors, records, units, qa_vectors)
        parts = [f"写入 {len(chunks)} 个块"]
        if records:
            parts.append(f"{len(records)} 行结构化数据")
        if units:
            parts.append(f"{len(units)} 条标准问答")
        note = "、".join(parts)
        if needs_review:
            note += "；平台公共知识需审核通过后才可被检索"
            if version > 1:
                note += f"，审核通过前旧版本 v{version - 1} 继续生效"
        elif version > 1:
            _supersede(doc_id, version)
            note += f"；旧版本 v{version - 1} 标记为已被替代"
        s["detail"] = note
    save("indexed")
    return result(len(leaf))


def _supersede(doc_id: str, version: int):
    with store.conn() as c:
        c.execute("UPDATE docs SET superseded = 1 WHERE doc_id = ? AND version < ?", (doc_id, version))


def reembed(version_id: str) -> None:
    with store.conn() as c:
        d = store.row(c.execute("SELECT * FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone())
        if not d:
            raise IngestError("文档不存在")
        if d["processing_policy"] == "local_only":
            raise IngestError("该文档处理位置策略为 local_only，不能发往云端向量化")
        rows = c.execute(
            "SELECT chunk_id, heading_path, text FROM chunks WHERE doc_version_id = ? AND kind != 'parent' ORDER BY seq",
            (version_id,),
        ).fetchall()
        units = [store.row(r) for r in c.execute("SELECT * FROM qa_units WHERE doc_version_id = ?", (version_id,))]
    texts = [(r["heading_path"] + "\n" + r["text"]).strip() for r in rows]
    qa_texts = [v for u in units for v in qa.variants(u)]
    if not texts and not qa_texts:
        raise IngestError("该文档没有需要向量化的内容")
    steps = [s for s in d["steps"] if s["name"] not in ("向量化", "建索引")]
    try:
        with _step(steps, "向量化") as s:
            allv = bailian.embed(texts + qa_texts)
            s["detail"] = f"{config.EMBED_MODEL}，{len(texts)} 个块" + (
                f" + {len(qa_texts)} 条问法" if qa_texts else ""
            ) + f"，{config.EMBED_DIM} 维"
    except bailian.BailianError as e:
        with store.conn() as c:
            c.execute(
                "UPDATE docs SET status='failed', error=?, steps=? WHERE doc_version_id=?",
                (str(e), json.dumps(steps, ensure_ascii=False), version_id),
            )
        raise
    vectors, qa_vectors = allv[: len(texts)], iter(allv[len(texts) :])
    with store.conn() as c:
        for r, v in zip(rows, vectors):
            c.execute("UPDATE chunks SET embedding = ? WHERE chunk_id = ?", (json.dumps(v), r["chunk_id"]))
        for u in units:
            embs = [next(qa_vectors) for _ in qa.variants(u)]
            c.execute("UPDATE qa_units SET embeddings = ? WHERE qa_id = ?", (json.dumps(embs), u["qa_id"]))
    if d["review_status"] == "approved" and d["version"] > 1:
        _supersede(d["doc_id"], d["version"])
    steps.append({"name": "建索引", "ok": True, "detail": "更新向量，可参与检索", "ms": 0})
    with store.conn() as c:
        c.execute(
            "UPDATE docs SET status='indexed', error=NULL, steps=? WHERE doc_version_id=?",
            (json.dumps(steps, ensure_ascii=False), version_id),
        )


def review(version_id: str, action: str) -> dict:
    with store.conn() as c:
        d = store.row(c.execute("SELECT * FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone())
    if not d:
        raise IngestError("文档不存在")
    if not meta.SPACES[d["knowledge_space_id"]]["review"]:
        raise IngestError("该知识空间无需审核")
    status = {"approve": "approved", "reject": "rejected"}[action]
    with store.conn() as c:
        c.execute("UPDATE docs SET review_status = ? WHERE doc_version_id = ?", (status, version_id))
    if status == "approved" and d["version"] > 1:
        _supersede(d["doc_id"], d["version"])
    return {"ok": True, "review_status": status}


def delete(version_id: str) -> None:
    with store.conn() as c:
        d = c.execute("SELECT doc_id FROM docs WHERE doc_version_id = ?", (version_id,)).fetchone()
        if not d:
            raise IngestError("文档不存在")
        for t in ("chunks", "table_rows", "qa_units", "docs"):
            c.execute(f"DELETE FROM {t} WHERE doc_version_id = ?", (version_id,))
        c.execute("UPDATE docs SET superseded = 0 WHERE doc_id = ?", (d["doc_id"],))
        rest = c.execute(
            "SELECT doc_version_id, version FROM docs WHERE doc_id = ? AND review_status = 'approved'"
            " ORDER BY version DESC LIMIT 1",
            (d["doc_id"],),
        ).fetchone()
        if rest:
            c.execute("UPDATE docs SET superseded = 1 WHERE doc_id = ? AND version < ?", (d["doc_id"], rest["version"]))


def _write(version_id, chunks, vectors, records, units, qa_vectors):
    ids = [f"{version_id}_c{i:04d}" for i in range(len(chunks))]
    vec_iter = iter(vectors or [])
    qv_iter = iter(qa_vectors or [])
    with store.conn() as c:
        for i, ch in enumerate(chunks):
            emb = None if ch.kind == "parent" or vectors is None else json.dumps(next(vec_iter))
            c.execute(
                "INSERT INTO chunks (chunk_id, doc_version_id, parent_chunk_id, kind, seq, text, tokens,"
                " heading_path, locator, embedding) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ids[i], version_id, ids[ch.parent] if ch.parent is not None else None, ch.kind, i, ch.text,
                 ch.tokens, ch.heading_path, ch.locator, emb),
            )
        for r in records:
            c.execute(
                "INSERT INTO table_rows (doc_version_id, sheet, row_no, data) VALUES (?,?,?,?)",
                (version_id, r["sheet"], r["row_no"], json.dumps({"fields": r["fields"], "extra": r["extra"]},
                                                                  ensure_ascii=False)),
            )
        for n, u in enumerate(units):
            embs = [next(qv_iter) for _ in qa.variants(u)] if qa_vectors is not None else None
            c.execute(
                "INSERT INTO qa_units (qa_id, doc_version_id, standard_question, similar_questions, answer, locator,"
                " embeddings) VALUES (?,?,?,?,?,?,?)",
                (f"{version_id}_q{n:03d}", version_id, u["standard_question"],
                 json.dumps(u["similar_questions"], ensure_ascii=False), u["answer"], u["locator"],
                 json.dumps(embs) if embs is not None else None),
            )


def _chunk_detail(cs, kt: str) -> str:
    s = STRATEGIES[kt]
    leaf = [c for c in cs if c.kind != "parent"]
    parents = len(cs) - len(leaf)
    sizes = [c.tokens for c in leaf] or [0]
    pc = f"，父块 {parents} 个" if parents else ""
    return f"{s['strategy']}（{s['size']}）：检索块 {len(leaf)} 个{pc}，长度 {min(sizes)}–{max(sizes)}"
