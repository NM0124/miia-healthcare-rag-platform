"""Central configuration. Every setting is read from environment variables / .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
WHO_DIR = DATA_DIR / "who"
NHM_DIR = DATA_DIR / "nhm"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name} (see .env.example)")
    return value


# --- Chroma Cloud (the only vector store) -----------------------------------
CHROMA_HOST = os.getenv("CHROMA_HOST", "api.trychroma.com")
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY", "")
CHROMA_TENANT = os.getenv("CHROMA_TENANT", "")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "")

WHO_COLLECTION = os.getenv("COLLECTION_NAME", "who_healthcare_guidelines")  # WHO + NHM PDFs
CDC_COLLECTION = os.getenv("CDC_COLLECTION", "cdc_scraped")                 # crawled CDC pages
USER_COLLECTION = os.getenv("USER_DOCS_COLLECTION", "user_documents")       # per-user uploads

# --- Models -----------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

# --- Chunking / retrieval ---------------------------------------------------
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 150))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", 4))  # per collection
RETRIEVAL_MODE = "dense"

# --- Supabase (users, chat history, document records) ------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

# --- Groq LLM ---------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# --- Auth -------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
SESSION_TTL_SECONDS = 7 * 24 * 3600

# --- Uploads ----------------------------------------------------------------
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", 20)) * 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}

# --- CDC crawler ------------------------------------------------------------
CDC_ROBOTS_URL = "https://www.cdc.gov/robots.txt"
CDC_SITEMAP_INDEX_URL = "https://www.cdc.gov/wcms-auto-sitemap-index.xml"
CRAWL_MANIFEST_PATH = Path(os.getenv("CRAWL_MANIFEST_PATH", DATA_DIR / "cdc_crawl_manifest.json"))
CRAWL_MAX_CONCURRENCY = int(os.getenv("CRAWL_MAX_CONCURRENCY", 3))
CRAWL_REQUEST_DELAY = float(os.getenv("CRAWL_REQUEST_DELAY", 0.8))
MONTHLY_CRON_SCHEDULE = os.getenv("MONTHLY_CRON_SCHEDULE", "0 2 1 * *")  # 1st of month, 02:00
