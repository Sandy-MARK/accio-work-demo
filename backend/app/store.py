"""SQLite 存储：文档版本与块。字段名对应 PRD 6.2 元数据字典。"""
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
    risk_level TEXT NOT NULL,
    processing_policy TEXT NOT NULL,
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
"""


def init() -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.RAW_DIR.mkdir(exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(docs)")}
        for col, default in [("risk_level", "normal"), ("processing_policy", "approved_cloud")]:
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
    if "steps" in d:
        d["steps"] = json.loads(d["steps"])
    if "embedding" in d:
        d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else None
    return d
