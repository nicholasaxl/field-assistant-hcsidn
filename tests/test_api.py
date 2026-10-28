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
from src.feedback import FeedbackStore
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
    feedback = FeedbackStore(":memory:")  # never touch the real data/feedback.db from tests
    monkeypatch.setattr(api_module, "get_feedback_store", lambda: feedback)
    test_client = TestClient(api_module.api)
    test_client.feedback = feedback
    return test_client


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
    assert stages[:2] == ["classify", "retrieve"] and stages[-2:] == ["format_citations", "apply_policy"]
    assert all(e["label"] for e in stream if e["type"] == "stage")

    final = stream[-1]
    assert final["type"] == "answer" and final["fallback"] is False
    steps = [b for b in final["blocks"] if b["kind"] == "step"]
    assert steps[0]["supported"] is True and steps[0]["cites"] == [1]
    assert steps[1]["supported"] is False  # invented step is flagged, not cited
    assert final["sources"][0]["kind"] == "document" and "distance" in final["sources"][0]
    assert final["strength"]["level"] == "check" and final["alerts"] == []

    logged = client.feedback.get_interaction(final["interaction_id"])  # every answer is recorded
    assert logged["question"] == "printer jam" and logged["steps"][0].startswith("Open the cover")
    assert logged["fallback"] == 0 and [s["node"] for s in logged["stages"]][0] == "classify"


def test_ask_with_nothing_indexed_falls_back(client):
    final = events(client.post("/api/ask", json={"question": "printer jam"}))[-1]
    assert final["type"] == "answer" and final["fallback"] is True and final["text"] == prompts.FALLBACK
    assert client.feedback.get_interaction(final["interaction_id"])["fallback"] == 1  # a coverage gap is recorded


def ask_once(client, question="printer jam"):
    upload(client)
    return events(client.post("/api/ask", json={"question": question, "device_model": "all"}))[-1]


def test_feedback_flow_returns_a_handoff_only_when_it_did_not_fix(client):
    answer = ask_once(client)
    iid = answer["interaction_id"]

    fixed = client.post("/api/feedback", json={"interaction_id": iid, "outcome": "fixed"}).json()
    assert fixed == {"ok": True, "handoff": None}

    client.post("/api/steps", json={"interaction_id": iid, "index": 0, "result": "failed"})
    failed = client.post(
        "/api/feedback",
        json={"interaction_id": iid, "outcome": "not_fixed", "reason": "step_failed", "note": "latch stuck"},
    ).json()
    assert "Problem reported: printer jam" in failed["handoff"]
    assert "[DID NOT WORK]" in failed["handoff"] and "latch stuck" in failed["handoff"]
    assert client.get(f"/api/handoff/{iid}").json()["text"] == failed["handoff"]

    assert client.delete(f"/api/feedback/{iid}").json() == {"ok": True}  # undo
    assert client.feedback.get_interaction(iid)["outcome"] is None


def test_feedback_validates_and_reports_unknown_answers(client):
    assert client.post("/api/feedback", json={"interaction_id": "x", "outcome": "fixed"}).status_code == 404
    assert client.get("/api/handoff/x").status_code == 404
    assert client.delete("/api/feedback/x").status_code == 404
    bad_outcome = client.post("/api/feedback", json={"interaction_id": "x", "outcome": "great"})
    bad_reason = client.post("/api/feedback", json={"interaction_id": "x", "outcome": "not_fixed", "reason": "meh"})
    assert bad_outcome.status_code == 422 and bad_reason.status_code == 422
    assert client.post("/api/steps", json={"interaction_id": "x", "index": -1, "result": "done"}).status_code == 422


def test_insights_sample_mode_export_and_clear(client):
    answer = ask_once(client)
    client.post("/api/feedback", json={"interaction_id": answer["interaction_id"], "outcome": "fixed"})
    real = client.get("/api/insights").json()
    assert real["sample"] is False and real["questions"] == 1 and real["fixed"] == 1

    assert client.post("/api/insights/sample").json()["loaded"] > 0
    sample = client.get("/api/insights?minutes=40").json()
    assert sample["sample"] is True and sample["minutes_per_escalation"] == 40 and sample["questions"] > 20
    assert "printer jam" not in str(sample)  # sample view never shows the real row
    assert client.get("/api/insights/export.csv").headers["content-type"].startswith("text/csv")

    assert client.delete("/api/insights/sample").json()["removed"] > 0
    assert client.get("/api/insights").json()["questions"] == 1
    assert client.delete("/api/insights/data").json()["removed"] == 1
    assert client.get("/api/insights").json()["questions"] == 0


def test_scorecard_endpoint_reports_when_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOCS_DIR", tmp_path)
    assert client.get("/api/scorecard").json() == {"available": False}
    (tmp_path / "scorecard.json").write_text('{"date": "2026-10-28", "retrieval_hit_rate": 0.9}', encoding="utf-8")
    assert client.get("/api/scorecard").json() == {"available": True, "date": "2026-10-28", "retrieval_hit_rate": 0.9}


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
