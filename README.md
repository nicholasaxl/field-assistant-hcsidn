# Field Support Assistant

A fully local RAG assistant for POS, ATM and kiosk field engineers. It answers troubleshooting questions from manuals, runbooks and an error-code table, and cites its sources. No API key, no cloud, no cost.

All sample content in `data/` is synthetic (fictional HX-POS-200, HX-ATM-500, HX-KIOSK-300 devices). Do not index customer data.

## How it works

```
upload / data/manuals -> loader -> split -> embed (Ollama) -> Chroma (vectorstore/)

question -> classify -> (error code?) exact lookup in error_codes.csv
                     -> retrieve -> grade -> generate (with [n] citations) -> sources list
                           ^           |
                        rewrite <------+ (weak results, max 2 retries) -> fallback "not found, escalate"
```

- Routing is plain Python (`src/graph.py`); the LLM only grades, rewrites queries and writes the answer. Small local models are unreliable at tool calling, so nothing depends on it.
- Error codes (e.g. `P-1002`) are looked up exactly in `data/error_codes.csv`, not by semantic search.
- Citations are computed, not trusted: small models invent source numbers, so `src/citations.py` strips the model's own `[n]` markers and attaches the sources whose text actually contains each step. A step that matches no source is left uncited and flagged "verify before acting".
- The relevance grader skips exact error-code matches, and it can prune lower-ranked chunks but cannot veto the top-ranked one (only an explicit NONE rejects everything, which triggers the "not found" fallback).
- Device-model filter: choosing a model searches chunks tagged for it plus chunks tagged `all`.

## Document loader

`src/loader.py` supports **PDF, DOCX, MD, TXT, CSV**. Each file becomes Documents with metadata `source`, `doc_type`, `page` or `section`, `device_model` and a content hash.

- Markdown/text can set the device in front matter (`---` / `device_model: HX-POS-200` / `---`).
- Re-indexing an unchanged file is skipped; a changed file replaces its old chunks (no duplicates).
- Scanned PDFs with no text layer are rejected with a clear message (OCR is not included).
- To add a format: write `_load_xxx(path)` and register it in `LOADERS`.
- In the UI, use the sidebar: pick or type a device tag, upload files (max 50 MB each), click **Index uploaded files**. The table below lists indexed documents and lets you remove one.
- In bulk: `python -m src.ingest --dir data/manuals`.

## Setup (Windows)

1. Install [Ollama](https://ollama.com/download) and pull the models (CPU-friendly sizes):
   ```
   ollama pull qwen2.5:3b
   ollama pull nomic-embed-text
   ```
2. Create the environment (already done if you used the scaffold):
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Index the sample documents, then start the app:
   ```
   .venv\Scripts\python -m src.ingest
   .venv\Scripts\python -m streamlit run app.py
   ```

Expect roughly 10-30 seconds per answer on a CPU-only laptop.

## Tests and evaluation

```
.venv\Scripts\python -m pytest -q          # no Ollama needed (fake LLM and embeddings)
.venv\Scripts\python -m src.evaluate       # retrieval hit rate on tests/eval_questions.json (needs Ollama)
```

## Swapping models

All model settings are in `config.py` and can be overridden with environment variables, for example:

```
set CHAT_MODEL=llama3.2:3b
set EMBED_MODEL=nomic-embed-text
```

If you change the embedding model, delete the `vectorstore/` folder and re-index.

## Limitations

- Answer quality is bounded by the small local model; a larger local model improves it.
- No authentication or multi-user support; it is a single-user prototype.
- Table-heavy PDFs may chunk poorly.
