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
# Seconds Ollama keeps a model in memory after its last use. Ollama's default (5 minutes) means the
# first question after a short break pays a ~25 s reload on CPU.
KEEP_ALIVE = int(os.getenv("KEEP_ALIVE", "1800"))

# Chunking and retrieval
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 4
MAX_RETRIES = 2  # query rewrites before giving up
# If even the best chunk is farther than this (Chroma L2 distance), the question is treated as
# out of scope. Tuned for nomic-embed-text on the sample docs (in-scope 0.4-0.8, unrelated 0.95+);
# re-tune with `python -m src.evaluate` if you change the embedding model.
RELEVANCE_MAX_DISTANCE = float(os.getenv("RELEVANCE_MAX_DISTANCE", "0.88"))

# Uploads
MAX_UPLOAD_MB = 50
ALL_DEVICES = "all"
