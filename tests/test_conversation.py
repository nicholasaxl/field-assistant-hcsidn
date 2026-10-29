import json

import pytest
from langchain_core.documents import Document

import config
from src import api as api_module
from src import prompts
from src.conversation import contextualize, is_follow_up, is_vague, tied_devices
from src.error_lookup import ErrorCodeDB
from src.graph import ask, build_graph

HISTORY = [{"question": "How do I clear a note jam?", "device": "HX-ATM-500", "sources": ["atm.md, Jam"]}]


# ---------- rules ----------
@pytest.mark.parametrize(
    "text",
    ["That didn't work", "still jammed", "What if it keeps happening?", "and the kiosk?", "why", "step 3 is unclear", "It still fails"],
)
def test_short_or_cued_questions_after_an_answer_are_follow_ups(text):
    assert is_follow_up(text, HISTORY)


@pytest.mark.parametrize(
    "text",
    [
        "How do I replace the receipt printer paper roll on the point of sale terminal?",  # long: stands alone
        "Kiosk shows K-1001",  # a new error code starts a new problem
        "Card reader is not detected",  # no cue, long enough to stand alone
        "how do i clean my toilet",  # few keywords but a full, unrelated question: must not borrow the last turn
        "how do i apply to universities",
    ],
)
def test_questions_that_stand_on_their_own_are_not_follow_ups(text):
    assert not is_follow_up(text, HISTORY)


def test_nothing_is_a_follow_up_without_history():
    assert not is_follow_up("That didn't work", [])


def test_contextualize_builds_a_standalone_question_and_carries_the_device():
    plain = contextualize("What about the kiosk?", HISTORY)
    assert plain["question"] == "How do I clear a note jam. What about the kiosk?" and plain["exclude"] == []
    assert plain["failure"] is False and plain["device"] == "HX-ATM-500"

    failed = contextualize("That didn't work", HISTORY)
    assert failed["failure"] is True and "escalate if the problem persists" in failed["question"]
    assert failed["exclude"] == ["atm.md, Jam"]  # don't offer the same passage again
    assert contextualize("Card reader is not detected", HISTORY) is None


def test_only_the_last_three_turns_matter():
    many = [{"question": f"q{i}", "device": "all", "sources": []} for i in range(6)]
    assert contextualize("That didn't work", many)["question"].startswith("q5.")


def test_vague_questions_and_device_ties():
    assert is_vague("help") and is_vague("broken") and not is_vague("P-1002") and not is_vague("printer is jammed")

    def doc(device, distance):
        return Document(page_content="x", metadata={"device_model": device, "distance": distance})

    assert tied_devices([doc("HX-ATM-500", 0.62), doc("HX-POS-200", 0.63)]) == ["HX-ATM-500", "HX-POS-200"]
    assert tied_devices([doc("HX-ATM-500", 0.62), doc("HX-POS-200", 0.75)]) == []  # clear winner
    assert tied_devices([doc("HX-ATM-500", 0.40), doc("HX-POS-200", 0.41)]) == []  # strong match: just answer
    assert tied_devices([doc("HX-ATM-500", 0.62), doc("all", 0.62)]) == []  # shared docs aren't a device choice
    assert tied_devices([doc("HX-ATM-500", 0.62), doc("HX-ATM-500", 0.63)]) == []  # one device only
    far = config.RELEVANCE_MAX_DISTANCE + 0.2
    assert tied_devices([doc("HX-ATM-500", far), doc("HX-POS-200", far + 0.01)]) == []  # unanswerable: refuse, don't ask


# ---------- graph ----------
class RecordingLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        if prompt.startswith("You are checking"):
            return "1"
        if prompt.startswith("Rewrite this"):
            return "note jam"
        return "Escalate to level 2."


def passage(label_source, section, distance, device="HX-ATM-500", text="Escalate to level 2 if it repeats."):
    return Document(
        page_content=text,
        metadata={"source": label_source, "section": section, "distance": distance, "device_model": device},
    )


def make_app(docs, devices=("HX-ATM-500", "HX-POS-200", "HX-KIOSK-300")):
    seen = []

    def retrieve_fn(query, device):
        seen.append((query, device))
        return list(docs)

    llm = RecordingLLM()
    graph = build_graph(llm, retrieve_fn, ErrorCodeDB(), known_devices_fn=lambda: list(devices), fast_path=False)
    return graph, llm, seen


def run(graph, question, history=None, device="all", infer=True):
    return graph.invoke({"question": question, "device_model": device, "history": history or [], "infer_device": infer})


def test_a_failed_procedure_searches_again_and_skips_what_was_already_shown():
    jam = passage("atm.md", "Jam", 0.5)
    escalation = passage("atm.md", "Escalation", 0.6)
    graph, _llm, seen = make_app([jam, escalation])
    state = run(graph, "That didn't work", HISTORY)
    assert state["followup"] and state["failure_followup"]
    assert [s["label"] for s in state["sources"]] == ["atm.md, Escalation"]  # not the Jam passage again
    query, device = seen[0]
    assert query.startswith("How do I clear a note jam.") and device == "HX-ATM-500"  # context and device carried over
    assert any(t.startswith("contextualize") for t in state["trace"])


def test_running_out_of_documented_steps_says_so_instead_of_repeating_itself():
    graph, _llm, _seen = make_app([passage("atm.md", "Jam", 0.5)])
    state = run(graph, "That didn't work", HISTORY)
    assert state["answer"] == prompts.EXHAUSTED and state["answer"] != prompts.FALLBACK


def test_a_new_question_is_not_treated_as_a_follow_up():
    graph, _llm, seen = make_app([passage("atm.md", "Jam", 0.5)])
    state = run(graph, "Card reader is not detected", HISTORY)
    assert not state["followup"] and seen[0][0] == "Card reader is not detected"


def test_a_near_tie_between_devices_asks_which_one_without_calling_the_model():
    graph, llm, _ = make_app([passage("a.md", "Jam", 0.62, "HX-ATM-500"), passage("p.md", "Jam", 0.63, "HX-POS-200")])
    state = run(graph, "paper jam")
    assert state["clarify"]["options"] == ["HX-ATM-500", "HX-POS-200"] and llm.calls == []
    assert state["clarify"]["kind"] == "device"
    assert state["answer"] == "" and "apply_policy" not in str(state["trace"])


def test_an_unrelated_question_is_refused_not_turned_into_a_device_question():
    far = config.RELEVANCE_MAX_DISTANCE + 0.1
    graph, _llm, _ = make_app([passage("a.md", "Jam", far, "HX-ATM-500"), passage("p.md", "Jam", far + 0.01, "HX-POS-200")])
    state = run(graph, "What is the best recipe for sourdough bread?")
    assert not state.get("clarify") and state["answer"] == prompts.FALLBACK


def test_a_vague_question_asks_for_detail_and_offers_the_known_devices():
    graph, _llm, _ = make_app([passage("a.md", "Jam", 0.62)])
    state = run(graph, "help")
    assert state["clarify"]["options"] == ["HX-ATM-500", "HX-POS-200", "HX-KIOSK-300"]
    assert "which device" in state["clarify"]["prompt"].lower() and state["clarify"]["kind"] == "detail"


@pytest.mark.parametrize(
    "kwargs",
    [{"device": "HX-ATM-500"}, {"infer": False}],
    ids=["device already chosen", "search all devices was requested"],
)
def test_no_clarifying_question_when_the_engineer_already_decided(kwargs):
    tie = [passage("a.md", "Jam", 0.62, "HX-ATM-500"), passage("p.md", "Jam", 0.63, "HX-POS-200")]
    graph, _llm, _ = make_app(tie)
    assert not run(graph, "paper jam", **kwargs).get("clarify")


def test_no_clarifying_question_for_a_strong_match_or_when_the_question_names_a_device():
    strong = [passage("a.md", "Jam", 0.40, "HX-ATM-500"), passage("p.md", "Jam", 0.41, "HX-POS-200")]
    graph, _llm, _ = make_app(strong)
    assert not run(graph, "paper jam").get("clarify")
    tie = [passage("a.md", "Jam", 0.62, "HX-ATM-500"), passage("p.md", "Jam", 0.63, "HX-POS-200")]
    graph, _llm, _ = make_app(tie)
    state = run(graph, "the ATM has a paper jam")  # "ATM" resolves it
    assert not state.get("clarify") and state["inferred_device"] == "HX-ATM-500"


# ---------- API ----------
def test_ask_rejects_too_much_or_malformed_history(client):
    turn = {"question": "q", "device": "all", "sources": []}
    assert client.post("/api/ask", json={"question": "x", "history": [turn] * 4}).status_code == 422
    assert client.post("/api/ask", json={"question": "x", "history": [{"device": "all"}]}).status_code == 422


def sse(response):
    return [json.loads(c[len("data: "):]) for c in response.text.split("\n\n") if c.startswith("data: ")]


def test_a_follow_up_is_answered_with_context_and_never_served_from_the_cache(client):
    history = [{"question": "printer jam", "device": "all", "sources": ["x.md, Jam"]}]
    body = {"question": "That didn't work", "history": history}
    first = sse(client.post("/api/ask", json=body))
    second = sse(client.post("/api/ask", json=body))
    assert [e["node"] for e in first if e["type"] == "stage"][0] == "contextualize"
    assert first[-1]["exhausted"] is True and first[-1]["fallback"] is True  # nothing indexed to try next
    assert first[-1]["text"] == prompts.EXHAUSTED and second[-1]["cached"] is False
    assert first[-1]["asked"].startswith("printer jam.")  # the standalone question, for the next follow-up


def test_a_question_that_stands_alone_hides_the_conversation_stage(client):
    final = sse(client.post("/api/ask", json={"question": "printer jam", "history": []}))
    assert "contextualize" not in [e.get("node") for e in final]


def test_a_clarifying_question_is_streamed_and_not_logged_as_an_answer(client, monkeypatch):
    class AskBack:
        def stream(self, state, stream_mode):
            yield {"clarify": {"clarify": {"prompt": "Which device are you working on?", "options": ["A", "B"]}}}

    monkeypatch.setattr(api_module, "get_resources", lambda: (None, None, AskBack()))
    events = sse(client.post("/api/ask", json={"question": "paper jam"}))
    assert events[-1]["type"] == "clarify" and events[-1]["options"] == ["A", "B"]
    assert client.get("/api/insights").json()["questions"] == 0  # a question back is not an answer
    assert config.ALL_DEVICES == "all"
