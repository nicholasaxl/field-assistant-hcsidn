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
- **Did this fix it?** Every answer ends with Fixed it / Didn't fix it. "Didn't fix it" asks what happened and produces a plain-text **handoff summary** (problem, device, error codes, the procedure suggested, which step failed, sources, the engineer's note) to copy to the next level of support. Answers with nothing found offer "Escalate with a summary".
- **Safety alerts.** Rules in `data/policies.json` (not the model) raise an alert for Critical error codes and risky topics: possible tampering, encryption keys, cash discrepancies, two-person cash work. For Critical alerts the procedure stays hidden behind "Show the documented procedure". Edit the file to change wording, keywords and the escalation contact.
- **Follow-ups.** After an answer, "That didn't work" or a short follow-up ("what about the kiosk?") is understood in context: the last three turns (question, device, sources shown) are sent with the question, and plain rules (`src/conversation.py`) rebuild a standalone search. When a procedure didn't work, the passages already shown are not offered again; if nothing else is documented the answer says so and offers a handoff summary. Memory is deliberately shallow because a small model with a 4,096-token window can't hold a long dialogue.
- **Clarifying questions.** Only when it would otherwise guess: a near-tie between two devices' passages ("Which device are you working on?" with one-tap choices) or a question too short to search on. Never on a follow-up, and never once a device is chosen.
- **Guided mode.** "Guide me step by step" walks the procedure one step at a time with Done / Didn't work. Results are saved, so Insights shows which steps fail most, and a failed step leads straight to a handoff summary. No model call is involved.
- **Open the original.** A source can open the original document (PDFs at the right page) from the Sources panel.
- **Insights.** Questions per day, what people ask about, fix rate (with how many answers actually got a response), an *estimated* engineer-time saving (answers fixed × minutes you set, never presented as a measurement), gaps in the library (questions with no answer or marked not fixed, grouped), per-document fix rate, the steps that fail most, and the last accuracy check. Data lives locally in `data/feedback.db`; Export CSV and Clear data are on the page. "Preview with sample data" fills the page with clearly labelled **invented** numbers for demos; it replaces the view until removed and never mixes with real data.
- Light and dark themes, keyboard focus states, reduced-motion support, responsive down to phone width.

## How it works

```
upload / data/manuals -> loader -> split -> embed (Ollama) -> Chroma (vectorstore/)

question -> classify -> (error code?) exact lookup in error_codes.csv
                     -> retrieve -> grade -> generate -> verify citations -> safety check
                           ^           |                                        ^
                        rewrite <------+ (nothing close, max 2 retries) -> "not found, escalate"
```

- Routing is plain Python (`src/graph.py`); the model only prunes, rewrites queries and writes the answer. Small local models are unreliable at tool calling, so nothing depends on it.
- Error codes (e.g. `P-1002`) are looked up exactly in `data/error_codes.csv`, not by semantic search.
- "Is this answerable from the documents?" is decided by retrieval distance (`RELEVANCE_MAX_DISTANCE` in `config.py`), not by the small model. The grader only prunes lower-ranked chunks and can never veto the best one. If you change the embedding model, re-tune the threshold with `python -m src.evaluate`.
- Citations are computed, not trusted: `src/citations.py` strips the model's own `[n]` markers and attaches the sources whose text actually contains each step.
- Models stay loaded for `KEEP_ALIVE` seconds (default 30 minutes) and are warmed at startup, so the first question doesn't pay a reload.
- The safety check (`src/policy.py`) runs on every path, including "not found", and is plain rules over the question, the error-code severity and the answer text.
- The "Strong / Good / Check the sources" chip is derived from the best match distance and whether every step traced to a source. It is a label, never a percentage.
- Every answer is logged to `data/feedback.db` (question, device, steps, sources, timings) so Insights has a real denominator. Nothing leaves the machine.

### Speed and retrieval (no model upgrade)

- **Fast path** (`src/fastpath.py`): when the best passage is a close match and holds a complete numbered procedure, the steps are shown verbatim and both model calls are skipped (answers in a few seconds, every step traceable, tagged "Copied from the manual"). For an error code it only uses a passage that actually names that code. Anything less certain takes the normal model path. Turn it off with `FAST_PATH=0`.
- **Skipped relevance check**: on a strong match the small model's relevance call is replaced by a distance rule.
- **Saved answers**: an in-memory cache returns a repeated question instantly. It is keyed on the question, device, library version, safety rules and settings, so adding or removing a document invalidates it.
- **Stop really stops**: closing the stream stops the agent before its next stage starts.
- **Stricter retries**: if nothing is close enough the question is reworded and searched again, but a reworded query must match more tightly than the original (`REWRITE_TIGHTEN`), and a question far from every document skips the retry (`REWRITE_MAX_OVERSHOOT`). This stops the model rewording an unrelated question into a false match.
- **Hybrid search** (`src/retriever.py`): vector search is fused with BM25 keyword search (reciprocal rank fusion) so part numbers and codes in prose match exactly. The best vector hit is always kept, because its distance decides whether a question is answerable; keyword-only hits carry no distance and can never make an unrelated question look answerable. Turn it off with `HYBRID_SEARCH=0`.
- **Passage headers**: each passage is embedded with "device | document | section" (the original text is kept for display), so a section titled with an error code is found by that code. Documents indexed in an older format are re-indexed from their saved files at startup (`python -m src.ingest --reindex` does the same by hand). Tables up to 1,500 characters stay in one piece.
- **Glossary** (`data/glossary.json`): synonym groups such as note jam / cash jam / bill jam widen the search only; edit the file to match your own vocabulary.
- **Device inference**: with the selector on All devices, a question that says ATM, POS or kiosk (when exactly one such model exists), or that names an error code belonging to one device, searches that device first and says so, with a one-tap "Search all devices".

## Accuracy scorecard

`python -m src.evaluate` runs a fast retrieval-only check; `python -m src.evaluate --answers` runs every question end to end with the real model (about 10 minutes) and writes `docs/scorecard.md` and `docs/scorecard.json`, which the Insights page shows. The question set is `tests/eval_questions.json`: in-scope questions with the expected document and key phrases, unrelated questions that must be refused, error codes, and safety cases that must raise an alert. It measures the packaged sample library, so treat it as a regression guard and rough indicator, not a promise about your documents.

## Project layout

```
src/            agent (graph.py), loader, ingestion, retrieval, citations, safety rules (policy.py),
                feedback store, conversation rules, fast path, evaluator, FastAPI server (api.py)
web/            React + Vite + TypeScript frontend (motion for animation, fonts bundled locally)
data/           sample manuals, error-code table, policies.json, glossary.json, demo uploads
docs/           scorecard.md / scorecard.json (written by src.evaluate --answers), PITCH.md
tests/          Python tests (fake LLM and embeddings, no Ollama needed) and the evaluation questions
start.ps1       build the UI if needed and run the server
.github/        CI: backend tests and a frontend type-check/build on every push
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
.venv\Scripts\python -m src.evaluate       # retrieval-only scorecard (needs Ollama for embeddings)
.venv\Scripts\python -m src.evaluate --answers   # full end-to-end scorecard, writes docs/scorecard.*
```

## Configuration

All settings are in `config.py` and can be overridden with environment variables (`CHAT_MODEL`, `EMBED_MODEL`, `KEEP_ALIVE`, `RELEVANCE_MAX_DISTANCE`, `STRONG_DISTANCE`, `FAST_PATH`, `FAST_PATH_DISTANCE`, `HYBRID_SEARCH`, `CACHE_SIZE`, `MINUTES_PER_ESCALATION`, `OLLAMA_BASE_URL`). Safety rules and the escalation contact are in `data/policies.json`. If you change the embedding model, delete the `vectorstore/` folder and re-index.

## Limitations

- Answer quality is bounded by the small local model; a larger local model improves it.
- No authentication or multi-user support; it is a single-user prototype meant for a trusted machine or network.
- Table-heavy PDFs may chunk poorly.
- The match level in the Sources panel is a coarse reading of search distance, not a probability.
