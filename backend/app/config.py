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
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "0.4"))

RECALL_K = 30
TOP_K = 5
RRF_K = 60

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "kb.sqlite3"
