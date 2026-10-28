import json
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

import config
from src import api as api_module
from src import prompts
from src.error_lookup import ErrorCodeDB
from src.graph import build_graph
from src.retriever import retrieve


class ScriptedLLM:
    def invoke(self, prompt):
        if prompt.startswith("You are checking"):
            return "1"
        if prompt.startswith("Rewrite this"):
            return "printer jam"
        return "1. Open the cover and remove the paper.\n2. Reboot the mainframe."


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = Chroma(
        collection_name=f"api_{uuid.uuid4().hex}", embedding_function=DeterministicFakeEmbedding(size=32)
    )
    code_db = ErrorCodeDB()
    graph = build_graph(ScriptedLLM(), lambda q, device: retrieve(q, store, device), code_db)
    monkeypatch.setattr(api_module, "get_resources", lambda: (store, code_db, graph))
    monkeypatch.setattr(config, "MANUALS_DIR", tmp_path / "manuals")
    monkeypatch.setattr(config, "RELEVANCE_MAX_DISTANCE", 100.0)  # fake embeddings have no real geometry
    return TestClient(api_module.api)


def events(response):
    return [json.loads(chunk[len("data: "):]) for chunk in response.text.split("\n\n") if chunk.startswith("data: ")]


def upload(client, name="runbook.md", text="# Jam\nOpen the cover and remove the paper.\n", tag="HX-POS-200"):
    return client.post(
        "/api/documents",
        files=[("files", (name, text.encode(), "text/markdown"))],
        data={"device_model": tag},
    )


def test_upload_list_and_delete(client):
    result = upload(client).json()["results"][0]
    assert result["status"] == "added" and result["chunks"] >= 1
    assert upload(client).json()["results"][0]["status"] == "skipped"

    listing = client.get("/api/documents").json()
    assert [d["source"] for d in listing["documents"]] == ["runbook.md"]
    assert ".pdf" in listing["extensions"]
    assert "HX-POS-200" in client.get("/api/devices").json()
    assert (config.MANUALS_DIR / "runbook.md").exists()

    assert client.delete("/api/documents/runbook.md").json()["removed"] == "runbook.md"
    assert client.get("/api/documents").json()["documents"] == []
    assert not (config.MANUALS_DIR / "runbook.md").exists()
    assert client.delete("/api/documents/runbook.md").status_code == 404


def test_bad_uploads_are_reported_per_file(client):
    exe = client.post("/api/documents", files=[("files", ("tool.exe", b"MZ", "application/octet-stream"))]).json()
    assert exe["results"][0]["status"] == "error" and "unsupported" in exe["results"][0]["message"]
    blank = upload(client, name="blank.md", text="   \n").json()["results"][0]
    assert blank["status"] == "error"
    assert not (config.MANUALS_DIR / "blank.md").exists()  # unindexable file not left behind


def test_delete_cannot_reach_files_outside_the_library(client):
    config.MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    outside = config.MANUALS_DIR.parent / "secret.md"
    outside.write_text("keep me", encoding="utf-8")
    for attempt in ("..%2Fsecret.md", "%2E%2E%2Fsecret.md", "..%5Csecret.md"):
        response = client.delete(f"/api/documents/{attempt}")
        assert response.status_code in (400, 404, 405)  # whichever layer rejects it
    assert outside.read_text(encoding="utf-8") == "keep me"


def test_ask_streams_stages_then_structured_answer(client):
    upload(client)
    response = client.post("/api/ask", json={"question": "printer jam", "device_model": "all"})
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = events(response)
    stages = [e["node"] for e in stream if e["type"] == "stage"]
    assert stages[:2] == ["classify", "retrieve"] and stages[-1] == "format_citations"
    assert all(e["label"] for e in stream if e["type"] == "stage")

    final = stream[-1]
    assert final["type"] == "answer" and final["fallback"] is False
    steps = [b for b in final["blocks"] if b["kind"] == "step"]
    assert steps[0]["supported"] is True and steps[0]["cites"] == [1]
    assert steps[1]["supported"] is False  # invented step is flagged, not cited
    assert final["sources"][0]["kind"] == "document" and "distance" in final["sources"][0]


def test_ask_with_nothing_indexed_falls_back(client):
    final = events(client.post("/api/ask", json={"question": "printer jam"}))[-1]
    assert final["type"] == "answer" and final["fallback"] is True and final["text"] == prompts.FALLBACK


def test_ask_validates_input(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422


def test_ask_reports_errors_as_events(client, monkeypatch):
    class Boom:
        def stream(self, *args, **kwargs):
            raise ConnectionError("connection refused")
            yield  # pragma: no cover

    monkeypatch.setattr(api_module, "get_resources", lambda: (None, None, Boom()))
    final = events(client.post("/api/ask", json={"question": "printer jam"}))[-1]
    assert final == {"type": "error", "message": "Can't reach the local model. Start Ollama, then try again."}


def test_health(client, monkeypatch):
    monkeypatch.setattr(api_module, "probe_ollama", lambda: [f"{config.CHAT_MODEL}", f"{config.EMBED_MODEL}:latest"])
    assert client.get("/api/health").json()["ready"] is True
    monkeypatch.setattr(api_module, "probe_ollama", lambda: None)
    assert client.get("/api/health").json() == {
        "ollama": False,
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "ready": False,
    }
