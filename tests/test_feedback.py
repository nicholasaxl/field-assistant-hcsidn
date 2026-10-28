from datetime import datetime, timedelta

import pytest

from src.feedback import FeedbackStore

NOW = datetime(2026, 10, 28, 12, 0)


@pytest.fixture
def store():
    return FeedbackStore(":memory:")


def log(store, question="How do I clear a note jam?", **kw):
    defaults = dict(
        question=question,
        device="HX-ATM-500",
        intent="troubleshooting",
        elapsed=12.0,
        steps=["Open the door.", "Remove the cassette.", "Run the test."],
        sources=["atm_runbook.md, Clearing a note jam"],
        ts=NOW.timestamp(),
    )
    defaults.update(kw)
    return store.log_interaction(**defaults)


def test_outcome_roundtrip_undo_and_validation(store):
    a = log(store)
    store.set_outcome(a, "not_fixed", "step_failed", "  door was stuck  ")
    item = store.get_interaction(a)
    assert (item["outcome"], item["reason"], item["note"]) == ("not_fixed", "step_failed", "door was stuck")

    store.set_outcome(a, "fixed")  # changing your mind overwrites, it doesn't duplicate
    assert store.get_interaction(a)["outcome"] == "fixed"
    store.clear_outcome(a)
    assert store.get_interaction(a)["outcome"] is None

    with pytest.raises(ValueError):
        store.set_outcome(a, "great")
    with pytest.raises(ValueError):
        store.set_outcome(a, "not_fixed", "bored")
    with pytest.raises(KeyError):
        store.set_outcome("missing", "fixed")


def test_handoff_summary_lists_steps_failures_and_note(store):
    a = log(store, codes=["A-1001"], alerts=[{"title": "Two-person control", "message": "Never alone."}])
    store.set_step_result(a, 0, "done")
    store.set_step_result(a, 1, "failed")
    store.set_outcome(a, "escalated", "need_person", "Cassette will not release")
    text = store.handoff_summary(a)
    assert "Problem reported: How do I clear a note jam?" in text
    assert "Error codes: A-1001" in text
    assert "1. Open the door.  [done]" in text
    assert "2. Remove the cassette.  [DID NOT WORK]" in text
    assert "3. Run the test." in text and "[" not in text.split("3. Run the test.")[1].split("\n")[0]
    assert "Outcome: Escalated (Needs a person)" in text
    assert "Engineer note: Cassette will not release" in text
    assert "atm_runbook.md, Clearing a note jam" in text and "Two-person control" in text
    store.set_step_result(a, 1, None)  # un-marking removes the flag
    assert "DID NOT WORK" not in store.handoff_summary(a)


def test_handoff_for_a_question_with_no_answer(store):
    a = log(store, fallback=True, steps=[], sources=[])
    assert "No matching procedure was found" in store.handoff_summary(a)


def test_insights_counts_rates_and_estimate(store):
    a, b, c, d = (log(store, f"q{i}") for i in range(4))
    nothing = log(store, "unknown thing", fallback=True, steps=[], sources=[])
    store.set_outcome(a, "fixed")
    store.set_outcome(b, "fixed")
    store.set_outcome(c, "not_fixed", "doc_wrong")
    store.set_step_result(c, 1, "failed")
    # d has no feedback; `nothing` is a coverage gap
    result = store.insights(days=30, minutes_per_escalation=30, now=NOW)

    assert result["sample"] is False and result["has_real"] is True
    assert (result["questions"], result["answered"], result["no_answer"]) == (5, 4, 1)
    assert result["feedback_count"] == 3
    assert result["fixed"] == 2 and result["not_fixed"] == 1 and result["escalated"] == 0
    assert result["fixed_rate"] == pytest.approx(2 / 3)
    assert result["feedback_coverage"] == pytest.approx(3 / 4)  # shown so the rate isn't over-trusted
    assert result["estimated_hours_saved"] == 1.0  # 2 fixed x 30 min
    assert result["median_seconds"] == 12.0
    assert result["volume"][-1] == {"date": "2026-10-28", "count": 5} and len(result["volume"]) == 30
    kinds = {g["question"]: g["kind"] for g in result["gaps"]}
    assert kinds == {"unknown thing": "no_answer", "q2": "not_fixed"}
    assert result["failing_steps"] == [{"step": "Remove the cassette.", "count": 1}]
    doc = result["documents"][0]
    assert doc["document"] == "atm_runbook.md" and doc["answers"] == 4 and doc["fix_rate"] == pytest.approx(2 / 3)


def test_repeated_gaps_are_grouped_with_a_count(store):
    for _ in range(3):
        log(store, "Scheduling the A-7001 patch window", fallback=True, steps=[], sources=[])
    log(store, "Something else", fallback=True, steps=[], sources=[])
    gaps = store.insights(now=NOW)["gaps"]
    assert gaps[0] == {
        "question": "Scheduling the A-7001 patch window",
        "device": "HX-ATM-500",
        "kind": "no_answer",
        "reason": None,
        "count": 3,
    }
    assert len(gaps) == 2 and gaps[1]["count"] == 1


def test_sample_data_is_mostly_answered(store):
    store.load_sample(now=NOW)
    view = store.insights(now=NOW)
    assert view["no_answer"] / view["questions"] < 0.2  # a believable demo, not a failing product


def test_insights_respects_the_period_and_handles_empty(store):
    assert store.insights(now=NOW)["fixed_rate"] is None  # no division by zero
    log(store, "old question", ts=(NOW - timedelta(days=40)).timestamp())
    assert store.insights(days=30, now=NOW)["questions"] == 0
    assert store.insights(days=60, now=NOW)["questions"] == 1


def test_sample_data_never_mixes_with_real_data(store):
    real = log(store, "my real question")
    store.set_outcome(real, "fixed")
    loaded = store.load_sample(now=NOW)
    assert loaded > 0 and store.load_sample(now=NOW) == 0  # loading twice adds nothing

    view = store.insights(now=NOW)
    assert view["sample"] is True and view["has_real"] is True
    assert "my real question" not in str(view)
    assert view["questions"] > 20 and view["fixed_rate"] is not None
    assert "sample" in store.export_csv().splitlines()[0] and ",yes" in store.export_csv()

    store.clear("sample")
    back = store.insights(now=NOW)
    assert back["sample"] is False and back["questions"] == 1  # real data untouched
    store.clear("all")
    assert store.insights(now=NOW)["questions"] == 0
    with pytest.raises(ValueError):
        store.clear("everything")


def test_sample_data_is_deterministic(store):
    other = FeedbackStore(":memory:")
    store.load_sample(now=NOW)
    other.load_sample(now=NOW)
    assert store.insights(now=NOW) == other.insights(now=NOW)


def test_export_csv_escapes_and_labels(store):
    a = log(store, 'Why, "exactly", does it jam?')
    store.set_outcome(a, "fixed")
    lines = store.export_csv().splitlines()
    assert lines[0].startswith("time,device,question")
    assert '"Why, ""exactly"", does it jam?"' in lines[1] and lines[1].endswith(",no")
