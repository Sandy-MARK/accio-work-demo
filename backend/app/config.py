import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip("/")

EMBED_MODEL = "text-embedding-v4"
EMBED_DIM = 1024
EMBED_BATCH = 10

RERANK_MODEL = "qwen3-rerank"
RERANK_TIMEOUT = float(os.getenv("RERANK_TIMEOUT", "2"))
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "0.5"))

RECALL_K = 30
TOP_K = 5
RRF_K = 60

# 标准问答库：单条 ≥0.85 直答；多条 ≥0.85 且第一、二名差 ≥0.03 取第一；差 <0.03 由用户选；0.70–0.85 给候选并走 RAG
QA_DIRECT = 0.85
QA_GAP = 0.03
QA_SUGGEST = 0.70
QA_TOP_K = 3

CRAWL_MAX_PAGES = 30

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "kb.sqlite3"
