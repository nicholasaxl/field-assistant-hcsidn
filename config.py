"""Single place for paths and model settings. Swap models here (or via env vars)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MANUALS_DIR = DATA_DIR / "manuals"
ERROR_CODES_CSV = DATA_DIR / "error_codes.csv"
POLICIES_JSON = DATA_DIR / "policies.json"
GLOSSARY_JSON = DATA_DIR / "glossary.json"
MODEL_SETTINGS_JSON = DATA_DIR / "model_settings.json"  # which model is active (never contains a key)
FEEDBACK_DB = DATA_DIR / "feedback.db"
DOCS_DIR = ROOT / "docs"
# Default for the Insights time-saved estimate: engineer minutes avoided per question that was fixed
# without calling a person. It is an assumption the user can edit in the UI, never a measurement.
MINUTES_PER_ESCALATION = int(os.getenv("MINUTES_PER_ESCALATION", "25"))
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
# A rewritten query must match this much more closely than the original (the model can rewrite an unrelated
# question into something that happens to sit near a document), and a question this far past the cutoff is not
# worth a retry at all.
REWRITE_TIGHTEN = float(os.getenv("REWRITE_TIGHTEN", "0.05"))
REWRITE_MAX_OVERSHOOT = float(os.getenv("REWRITE_MAX_OVERSHOOT", "0.12"))
# If even the best chunk is farther than this (Chroma L2 distance), the question is treated as
# out of scope. Tuned for nomic-embed-text on the sample docs (in-scope 0.4-0.8, unrelated 0.95+);
# re-tune with `python -m src.evaluate` if you change the embedding model.
RELEVANCE_MAX_DISTANCE = float(os.getenv("RELEVANCE_MAX_DISTANCE", "0.88"))
# Best-chunk distance at or below this counts as a "Strong match" in the UI.
STRONG_DISTANCE = float(os.getenv("STRONG_DISTANCE", "0.7"))

# Speed. The fast path shows a close-matching numbered procedure verbatim and skips both model calls.
FAST_PATH = os.getenv("FAST_PATH", "1") == "1"
FAST_PATH_DISTANCE = float(os.getenv("FAST_PATH_DISTANCE", "0.6"))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "64"))  # saved answers kept in memory; 0 turns the cache off

# Clarifying questions: ask "which device?" only when two devices' best passages are this close (and none is strong).
CLARIFY_MARGIN = float(os.getenv("CLARIFY_MARGIN", "0.04"))
CLARIFY_WEAK = float(os.getenv("CLARIFY_WEAK", "0.45"))

# Retrieval. Keyword (BM25) search is fused with vector search so part numbers and codes match exactly.
HYBRID_SEARCH = os.getenv("HYBRID_SEARCH", "1") == "1"
INDEX_VERSION = 2  # bump when the stored chunk format changes; stale documents are re-indexed on startup

# Uploads
MAX_UPLOAD_MB = 50
ALL_DEVICES = "all"
