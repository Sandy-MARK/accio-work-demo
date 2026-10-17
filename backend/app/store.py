"""SQLite 存储：文档版本、块、结构化表行、QA 单元、抓取来源。字段名对应 PRD 6.2 元数据字典。"""
import json
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    doc_version_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    knowledge_space_id TEXT NOT NULL,
    knowledge_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    market TEXT NOT NULL,
    language TEXT NOT NULL,
    business_domain TEXT NOT NULL,
    access_level TEXT NOT NULL,
    quality_grade TEXT NOT NULL,
    effective_from TEXT,
    expires_at TEXT,
    superseded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    steps TEXT NOT NULL DEFAULT '[]',
    parsed_md TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_version_id TEXT NOT NULL,
    parent_chunk_id TEXT,
    kind TEXT NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    heading_path TEXT NOT NULL,
    locator TEXT NOT NULL,
    origin_type TEXT NOT NULL DEFAULT 'original',
    embedding TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_version_id);
CREATE TABLE IF NOT EXISTS table_rows (
    doc_version_id TEXT NOT NULL,
    sheet TEXT NOT NULL,
    row_no INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rows_doc ON table_rows(doc_version_id);
CREATE TABLE IF NOT EXISTS qa_units (
    qa_id TEXT PRIMARY KEY,
    doc_version_id TEXT NOT NULL,
    standard_question TEXT NOT NULL,
    similar_questions TEXT NOT NULL,
    answer TEXT NOT NULL,
    locator TEXT NOT NULL,
    embeddings TEXT
);
CREATE INDEX IF NOT EXISTS idx_qa_doc ON qa_units(doc_version_id);
CREATE TABLE IF NOT EXISTS crawl_sources (
    source_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    mode TEXT NOT NULL,
    meta TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    last_result TEXT
);
"""

DOC_COLUMNS = [
    ("risk_level", "normal"),
    ("processing_policy", "approved_cloud"),
    ("review_status", "approved"),
    ("dept_ids", ""),
    ("pii_level", "none"),
    ("content_hash", ""),
    ("source_url", ""),
    ("table_kind", ""),
]


def init() -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.RAW_DIR.mkdir(exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(docs)")}
        for col, default in DOC_COLUMNS:
            if col not in cols:
                c.execute(f"ALTER TABLE docs ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("steps", "similar_questions", "data", "meta", "last_result"):
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    for k in ("embedding", "embeddings"):
        if k in d:
            d[k] = json.loads(d[k]) if d[k] else None
    return d
