# Field Assist

A fully local RAG assistant for POS, ATM and kiosk field engineers. It answers troubleshooting questions from manuals, runbooks and an error-code table, and shows exactly which source supports each step. No API key, no cloud, no cost.

All sample content in `data/` is synthetic (fictional HX-POS-200, HX-ATM-500, HX-KIOSK-300 devices). Do not index customer data.

## Run it

1. Install [Ollama](https://ollama.com/download) and pull the models (CPU-friendly sizes):
   ```
   ollama pull qwen2.5:3b
   ollama pull nomic-embed-text
   ```
2. Set up Python once:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\python -m src.ingest
   ```
3. Start the app (builds the UI the first time, needs Node 20+):
   ```
   .\start.ps1
   ```
   Open http://localhost:8000.

Expect roughly 10-25 seconds per answer on a CPU-only laptop.

## The interface

- **Live agent timeline.** Each stage streams in as it finishes (reading the question, searching, checking relevance, writing, verifying sources), then folds into a one-line summary.
- **Steps with proof.** Every step has a ring numeral: filled when a source contains it, dashed amber when none does ("check before acting"). Citation chips open that source in the Sources panel.
- **Sources panel.** The passages the answer was written from, a plain-language match level, and expandable excerpts.
- **Library.** Drag in PDF, DOCX, Markdown, TXT or CSV files, tag them with a device model, and add or remove documents. Re-adding an unchanged file is skipped.
- **Device switch.** Narrow answers to one device model; chunks tagged for all devices always stay in scope.
- Light and dark themes, keyboard focus states, reduced-motion support, responsive down to phone width.

## How it works

```
upload / data/manuals -> loader -> split -> embed (Ollama) -> Chroma (vectorstore/)

question -> classify -> (error code?) exact lookup in error_codes.csv
                     -> retrieve -> grade -> generate -> verify citations
                           ^           |
                        rewrite <------+ (nothing close, max 2 retries) -> "not found, escalate"
```

- Routing is plain Python (`src/graph.py`); the model only prunes, rewrites queries and writes the answer. Small local models are unreliable at tool calling, so nothing depends on it.
- Error codes (e.g. `P-1002`) are looked up exactly in `data/error_codes.csv`, not by semantic search.
- "Is this answerable from the documents?" is decided by retrieval distance (`RELEVANCE_MAX_DISTANCE` in `config.py`), not by the small model. The grader only prunes lower-ranked chunks and can never veto the best one. If you change the embedding model, re-tune the threshold with `python -m src.evaluate`.
- Citations are computed, not trusted: `src/citations.py` strips the model's own `[n]` markers and attaches the sources whose text actually contains each step.
- Models stay loaded for `KEEP_ALIVE` seconds (default 30 minutes) and are warmed at startup, so the first question doesn't pay a reload.

## Project layout

```
src/            agent, loader, ingestion, retrieval, citations, FastAPI server (api.py)
web/            React + Vite + TypeScript frontend (motion for animation, fonts bundled locally)
data/           sample manuals, error-code table, a demo upload
tests/          Python tests (fake LLM and embeddings, no Ollama needed)
start.ps1       build the UI if needed and run the server
```

## Document loader

`src/loader.py` supports **PDF, DOCX, MD, TXT, CSV**. Each file becomes Documents with metadata `source`, `doc_type`, `page` or `section`, `device_model` and a content hash.

- Markdown/text can set the device in front matter (`---` / `device_model: HX-POS-200` / `---`).
- Scanned PDFs with no text layer are rejected with a clear message (OCR is not included).
- To add a format: write `_load_xxx(path)` and register it in `LOADERS`.
- Bulk index from the command line: `python -m src.ingest --dir data/manuals`.

## Develop

Run the API and the UI dev server separately for hot reload:

```
.venv\Scripts\python -m uvicorn src.api:app --port 8000
cd web
npm install
npm run dev
```

The dev UI is at http://localhost:5173 and proxies `/api` to port 8000.

```
.venv\Scripts\python -m pytest -q          # backend, no Ollama needed
cd web; npm run build                      # type-checks the frontend, then bundles it
.venv\Scripts\python -m src.evaluate       # retrieval hit rate on tests/eval_questions.json (needs Ollama)
```

## Configuration

All model settings are in `config.py` and can be overridden with environment variables (`CHAT_MODEL`, `EMBED_MODEL`, `KEEP_ALIVE`, `RELEVANCE_MAX_DISTANCE`, `OLLAMA_BASE_URL`). If you change the embedding model, delete the `vectorstore/` folder and re-index.

## Limitations

- Answer quality is bounded by the small local model; a larger local model improves it.
- No authentication or multi-user support; it is a single-user prototype meant for a trusted machine or network.
- Table-heavy PDFs may chunk poorly.
- The match level in the Sources panel is a coarse reading of search distance, not a probability.
