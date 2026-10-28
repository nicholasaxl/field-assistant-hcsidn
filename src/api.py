"""HTTP API for the web UI: streamed agent answers, document library, health.

Run:  python -m uvicorn src.api:app --port 8000
In production the built frontend (web/dist) is served from the same process.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from src import prompts
from src.error_lookup import ErrorCodeDB
from src.feedback import FeedbackStore
from src.graph import build_default_app
from src.ingest import delete_document, get_store, ingest_file, list_documents
from src.loader import SUPPORTED_EXTENSIONS, validate_upload

def warm_up_models() -> None:
    """Load both models into memory so the first question doesn't wait for them. Best effort."""
    try:
        httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/embed",
            json={"model": config.EMBED_MODEL, "input": "warm up", "keep_alive": config.KEEP_ALIVE},
            timeout=120,
        )
        httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={"model": config.CHAT_MODEL, "keep_alive": config.KEEP_ALIVE},
            timeout=180,
        )
    except Exception:
        pass  # Ollama may not be running yet; the health pill tells the user


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=warm_up_models, daemon=True).start()
    yield


api = FastAPI(title="Field Assist API", lifespan=lifespan)

STAGE_LABELS = {
    "classify": "Reading the question",
    "lookup_code": "Matching the error code",
    "retrieve": "Searching the manuals",
    "grade": "Checking relevance",
    "rewrite": "Rephrasing the search",
    "generate": "Writing the answer",
    "format_citations": "Verifying sources",
    "apply_policy": "Safety check",
    "fallback": "Nothing relevant found",
}


@lru_cache(maxsize=1)
def get_resources():
    """(vector store, error-code table, compiled agent), built once on first use."""
    store = get_store()
    code_db = ErrorCodeDB()
    return store, code_db, build_default_app(store, code_db)


@lru_cache(maxsize=1)
def get_feedback_store() -> FeedbackStore:
    return FeedbackStore(config.FEEDBACK_DB)


def probe_ollama() -> list[str] | None:
    """Names of installed Ollama models, or None if the server is unreachable."""
    try:
        response = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        return [m["name"] for m in response.json().get("models", [])]
    except Exception:
        return None


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "connect" in text.lower() or "refused" in text.lower():
        return "Can't reach the local model. Start Ollama, then try again."
    return text or exc.__class__.__name__


def describe_stage(node: str, update: dict, state: dict) -> str:
    """One short, plain-language line about what a stage just did."""
    trace = update.get("trace") or [""]
    last = trace[-1]
    if node == "classify":
        if update.get("intent") == "error_code":
            codes = ", ".join(dict.fromkeys(r["code"] for r in update.get("code_records", [])))
            return f"Found error code {codes}"
        return "Troubleshooting question" if update.get("intent") == "troubleshooting" else "No question to answer"
    if node == "lookup_code":
        return "Using the exact entry from the error-code table"
    if node == "retrieve":
        count = len(update.get("docs", []))
        return f"{count} passage{'s' if count != 1 else ''} found"
    if node == "grade":
        if "skipped" in last:
            return "Exact code match, keeping all passages"
        if "out of scope" in last:
            return "Nothing close enough to the question"
        if "nothing retrieved" in last:
            return "Nothing retrieved"
        return f"Kept {len(update.get('docs', []))} of {len(state.get('docs', []))} passages"
    if node == "rewrite":
        return f"Trying: {update.get('query', '')}"
    if node == "generate":
        count = len(update.get("sources", []))
        return f"From {count} source{'s' if count != 1 else ''}"
    if node == "format_citations":
        blocks = update.get("blocks", [])
        steps = [b for b in blocks if b["kind"] == "step"]
        unverified = sum(1 for b in steps if not b["supported"])
        if unverified:
            return f"{len(steps) - unverified} of {len(steps)} steps traced to a source"
        return f"All {len(steps)} steps traced to a source" if steps else "Done"
    if node == "apply_policy":
        alerts = update.get("alerts", [])
        if not alerts:
            return "No safety alerts"
        return f"{len(alerts)} alert{'s' if len(alerts) != 1 else ''}: {alerts[0]['title']}"
    if node == "fallback":
        return "Try naming the device or error code"
    return ""


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def stream_answer(graph, question: str, device_model: str, feedback: FeedbackStore | None = None):
    started = time.perf_counter()
    state: dict = {"question": question, "device_model": device_model}
    stage_log: list[dict] = []
    try:
        for chunk in graph.stream(dict(state), stream_mode="updates"):
            for node, update in chunk.items():
                update = update or {}
                detail = describe_stage(node, update, state)
                state.update(update)
                at = round(time.perf_counter() - started, 1)
                stage_log.append({"node": node, "at": at})
                yield sse(
                    {
                        "type": "stage",
                        "node": node,
                        "label": STAGE_LABELS.get(node, node),
                        "detail": detail,
                        "at": at,
                    }
                )
        answer = state.get("answer", "")
        blocks = state.get("blocks", [])
        elapsed = round(time.perf_counter() - started, 1)
        fallback = answer == prompts.FALLBACK

        interaction_id = None
        if feedback is not None:
            try:  # logging must never break an answer
                interaction_id = feedback.log_interaction(
                    question=question,
                    device=device_model,
                    intent=state.get("intent"),
                    fallback=fallback,
                    elapsed=elapsed,
                    stages=stage_log,
                    steps=[b["text"] for b in blocks if b["kind"] == "step"],
                    sources=[s["label"] for s in state.get("sources", [])],
                    codes=[r["code"] for r in state.get("code_records", [])],
                    alerts=state.get("alerts", []),
                )
            except Exception:
                interaction_id = None

        yield sse(
            {
                "type": "answer",
                "interaction_id": interaction_id,
                "fallback": fallback,
                "intent": state.get("intent"),
                "text": answer,
                "blocks": blocks,
                "sources": state.get("sources", []),
                "alerts": state.get("alerts", []),
                "strength": state.get("strength"),
                "elapsed": elapsed,
            }
        )
    except Exception as exc:  # surface a readable message instead of a dropped stream
        yield sse({"type": "error", "message": friendly_error(exc)})


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    device_model: str = config.ALL_DEVICES


@api.post("/api/ask")
def ask(body: AskBody):
    _, _, graph = get_resources()
    return StreamingResponse(
        stream_answer(graph, body.question.strip(), body.device_model or config.ALL_DEVICES, get_feedback_store()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/api/health")
def health():
    names = probe_ollama()

    def installed(model: str) -> bool:
        return names is not None and any(n == model or n == f"{model}:latest" for n in names)

    return {
        "ollama": names is not None,
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "ready": installed(config.CHAT_MODEL) and installed(config.EMBED_MODEL),
    }


@api.get("/api/devices")
def devices():
    store, code_db, _ = get_resources()
    known = set(code_db.devices()) | {d["device_model"] for d in list_documents(store)}
    return sorted(known - {config.ALL_DEVICES})


@api.get("/api/documents")
def documents():
    store, _, _ = get_resources()
    return {"documents": list_documents(store), "extensions": SUPPORTED_EXTENSIONS, "max_mb": config.MAX_UPLOAD_MB}


@api.post("/api/documents")
def upload_documents(files: list[UploadFile] = File(...), device_model: str = Form(config.ALL_DEVICES)):
    store, _, _ = get_resources()
    tag = device_model.strip() or config.ALL_DEVICES
    config.MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for upload in files:
        name = upload.filename or "upload"
        content = upload.file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        try:
            safe_name = validate_upload(name, len(content))
            target = config.MANUALS_DIR / safe_name
            previous = target.read_bytes() if target.exists() else None
            target.write_bytes(content)
            try:
                result = ingest_file(target, store, tag)
            except Exception:
                # Don't leave an unindexable file behind (or clobber the previous good copy).
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(previous)
                raise
            results.append({"name": safe_name, "status": result.status, "chunks": result.chunks})
        except Exception as exc:
            results.append({"name": name, "status": "error", "message": friendly_error(exc)})
    return {"results": results}


@api.delete("/api/documents/{source}")
def remove_document(source: str):
    if Path(source).name != source:
        raise HTTPException(status_code=400, detail="Invalid document name")
    store, _, _ = get_resources()
    removed = delete_document(source, store)
    (config.MANUALS_DIR / source).unlink(missing_ok=True)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{source}' is not in the library")
    return {"removed": source, "chunks": removed}


class FeedbackBody(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=64)
    outcome: Literal["fixed", "not_fixed", "escalated"]
    reason: Literal["step_failed", "different_problem", "doc_wrong", "need_person"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class StepBody(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=64)
    index: int = Field(ge=0, le=200)
    result: Literal["done", "failed"] | None = None


@api.post("/api/feedback")
def post_feedback(body: FeedbackBody):
    feedback = get_feedback_store()
    try:
        feedback.set_outcome(body.interaction_id, body.outcome, body.reason, body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="That answer is no longer on record")
    handoff = feedback.handoff_summary(body.interaction_id) if body.outcome != "fixed" else None
    return {"ok": True, "handoff": handoff}


@api.delete("/api/feedback/{interaction_id}")
def undo_feedback(interaction_id: str):
    try:
        get_feedback_store().clear_outcome(interaction_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="That answer is no longer on record")
    return {"ok": True}


@api.post("/api/steps")
def post_step(body: StepBody):
    try:
        get_feedback_store().set_step_result(body.interaction_id, body.index, body.result)
    except KeyError:
        raise HTTPException(status_code=404, detail="That answer is no longer on record")
    return {"ok": True}


@api.get("/api/handoff/{interaction_id}")
def handoff(interaction_id: str):
    try:
        return {"text": get_feedback_store().handoff_summary(interaction_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="That answer is no longer on record")


@api.get("/api/insights")
def insights(days: int = Query(30, ge=1, le=365), minutes: int | None = Query(None, ge=0, le=600)):
    return get_feedback_store().insights(days=days, minutes_per_escalation=minutes)


@api.post("/api/insights/sample")
def load_sample():
    return {"loaded": get_feedback_store().load_sample()}


@api.delete("/api/insights/sample")
def remove_sample():
    return {"removed": get_feedback_store().clear("sample")}


@api.delete("/api/insights/data")
def clear_data():
    return {"removed": get_feedback_store().clear("all")}


@api.get("/api/insights/export.csv")
def export_insights():
    return Response(
        get_feedback_store().export_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="field-assist-insights.csv"'},
    )


@api.get("/api/scorecard")
def scorecard():
    """The last accuracy check written by `python -m src.evaluate --answers`, if any."""
    path = config.DOCS_DIR / "scorecard.json"
    if not path.exists():
        return {"available": False}
    return {"available": True, **json.loads(path.read_text(encoding="utf-8"))}


# Serve the built frontend last so /api routes win.
_DIST = config.ROOT / "web" / "dist"
if _DIST.exists():
    api.mount("/", StaticFiles(directory=_DIST, html=True), name="web")

app = api
