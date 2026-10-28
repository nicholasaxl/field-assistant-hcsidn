import json

import config
from src import api as api_module
from src import prompts


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


def test_original_documents_can_be_opened_read_only(client):
    upload(client, name="runbook.md")
    upload(client, name="manual.pdf", text="%PDF-1.4 minimal")  # not parseable, so it won't be indexed
    (config.MANUALS_DIR / "manual.pdf").write_bytes(b"%PDF-1.4 minimal")
    markdown = client.get("/api/files/runbook.md")
    assert markdown.status_code == 200 and "attachment" in markdown.headers["content-disposition"]
    pdf = client.get("/api/files/manual.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["content-disposition"].startswith("inline")
    assert client.get("/api/files/missing.md").status_code == 404
    assert client.get("/api/files/..%2Fconftest.py").status_code in (400, 404)
    assert client.put("/api/files/runbook.md").status_code in (404, 405)  # read-only


def test_sources_carry_the_file_and_page_so_the_ui_can_link_to_them(client):
    upload(client)
    final = events(client.post("/api/ask", json={"question": "printer jam"}))[-1]
    assert final["sources"][0]["file"] == "runbook.md" and "page" in final["sources"][0]


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


def test_a_repeated_question_is_answered_from_the_cache_until_the_documents_change(client, monkeypatch):
    first = events(client.post("/api/ask", json={"question": "printer jam"}))  # nothing indexed yet: fallback
    upload(client)  # indexing bumps the library version, so the earlier fallback is no longer reused
    second = events(client.post("/api/ask", json={"question": "printer jam"}))
    assert second[-1]["cached"] is False and second[-1]["fallback"] is False

    third = events(client.post("/api/ask", json={"question": "  Printer   JAM "}))  # same question, different spacing
    assert [e["node"] for e in third if e["type"] == "stage"] == ["cache"]
    assert third[-1]["cached"] is True and third[-1]["elapsed"] == 0.0
    assert third[-1]["blocks"] == second[-1]["blocks"]
    assert third[-1]["interaction_id"] != second[-1]["interaction_id"]  # each ask is its own record for feedback
    assert client.feedback.get_interaction(third[-1]["interaction_id"])["cached"] == 1

    client.delete("/api/documents/runbook.md")
    assert events(client.post("/api/ask", json={"question": "printer jam"}))[-1]["cached"] is False
    assert first[-1]["fallback"] is True


def test_answer_cache_is_a_bounded_lru():
    cache = api_module.AnswerCache(2)
    cache.put("a", {"v": 1})
    cache.put("b", {"v": 2})
    cache.get("a")  # a is now the most recently used
    cache.put("c", {"v": 3})
    assert cache.get("b") is None and cache.get("a") == {"v": 1} and cache.get("c") == {"v": 3}
    api_module.AnswerCache(0).put("x", {"v": 1})  # size 0 never stores


def test_stopping_the_stream_stops_the_agent_before_its_next_stage():
    import asyncio

    started = []

    def slow_events():
        for name in ["one", "two", "three", "four"]:
            started.append(name)
            yield name

    class Request:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 2  # the client leaves after receiving two events

    async def consume():
        return [item async for item in api_module.event_stream(Request(), slow_events())]

    assert asyncio.run(consume()) == ["one", "two"]
    assert started == ["one", "two"]  # stages three and four never began


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
