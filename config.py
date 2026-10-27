"""Single place for paths and model settings. Swap models here (or via env vars)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MANUALS_DIR = DATA_DIR / "manuals"
ERROR_CODES_CSV = DATA_DIR / "error_codes.csv"
VECTOR_DIR = ROOT / "vectorstore"
COLLECTION = "manuals"

# Local models served by Ollama. Any chat/embedding model Ollama can run works here.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:3b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
NUM_CTX = int(os.getenv("NUM_CTX", "4096"))

# Chunking and retrieval
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 4
MAX_RETRIES = 2  # query rewrites before giving up

# Uploads
MAX_UPLOAD_MB = 50
ALL_DEVICES = "all"
