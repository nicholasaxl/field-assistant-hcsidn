from langchain_core.documents import Document

import config
from src import prompts
from src.error_lookup import ErrorCodeDB
from src.graph import ask, build_graph


class FakeLLM:
    def __init__(self, grade_reply="1"):
        self.grade_reply = grade_reply
        self.calls: list[str] = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        if prompt.startswith("You are checking search results"):
            return self.grade_reply
        if prompt.startswith("Rewrite this"):
            return "printer paper jam"
        return "Open the cover and clear the jam [1]."


DOC = Document(page_content="Open the cover and remove the paper.", metadata={"source": "runbook.md", "section": "Jam"})


def make_app(llm, docs, max_retries=2):
    seen = []

    def retrieve_fn(query, device):
        seen.append(query)
        return list(docs)

    return build_graph(llm, retrieve_fn, ErrorCodeDB(), max_retries=max_retries), seen


def test_troubleshooting_path_cites_sources():
    llm = FakeLLM("1")
    app, _ = make_app(llm, [DOC])
    state = ask(app, "printer keeps jamming")
    assert state["intent"] == "troubleshooting"
    assert "**Sources**" in state["answer"] and "[1] runbook.md, Jam" in state["answer"]
    assert "generate" in state["trace"]
    assert "[1] runbook.md, Jam" in state["answer"]
    assert "[1]." not in state["answer"]  # the model's own marker is stripped; ours are computed


def test_error_code_path_skips_grading_and_keeps_runbook_context():
    llm = FakeLLM("NONE")  # would reject everything if the grader ran
    app, seen = make_app(llm, [DOC])
    state = ask(app, "Getting P-1002 on the terminal", "HX-POS-200")
    assert state["intent"] == "error_code"
    assert "Error code P-1002 (HX-POS-200)" in state["answer"]
    assert "[2] runbook.md, Jam" in state["answer"]  # retrieved chunk kept as extra context
    assert "paper jam" in seen[0].lower()  # query enriched with the record's meaning
    assert not any(c.startswith(("You are checking", "Rewrite this")) for c in llm.calls)
    assert any(t.startswith("grade: skipped") for t in state["trace"])


class FixedAnswerLLM(FakeLLM):
    def __init__(self, answer):
        super().__init__("1")
        self.answer = answer

    def invoke(self, prompt):
        if prompt.startswith("You are a support assistant"):
            return self.answer
        return super().invoke(prompt)


def test_steps_are_cited_by_content_and_unsupported_steps_are_flagged():
    answer_from_model = "1. Open the cover and remove the paper. [7]\n2. Reboot the mainframe immediately. [1]"
    app, _ = make_app(FixedAnswerLLM(answer_from_model), [DOC])
    state = ask(app, "printer jam")
    lines = state["answer"].splitlines()
    assert lines[0] == "1. Open the cover and remove the paper. [1]"  # invented [7] replaced by computed [1]
    assert lines[1] == "2. Reboot the mainframe immediately."  # model's [1] dropped: not in any source
    assert "1 step(s) could not be matched" in state["answer"]
    assert "citations: 1 step(s) matched, 1 unmatched" in state["trace"]
    assert state["strength"]["level"] == "check"  # an untraceable step means "check the sources"


NEAR = Document(
    page_content="Open the cover and remove the paper.",
    metadata={"source": "runbook.md", "section": "Jam", "distance": config.RELEVANCE_MAX_DISTANCE - 0.1},
)
FAR = Document(
    page_content="Unrelated text.",
    metadata={"source": "other.md", "section": "X", "distance": config.RELEVANCE_MAX_DISTANCE + 0.1},
)


def test_grader_none_cannot_reject_a_close_match():
    llm = FakeLLM("NONE")  # the real 3B model said this for "How do I clear a note jam?"
    app, _ = make_app(llm, [NEAR, FAR])
    state = ask(app, "How do I clear a note jam?")
    assert [s["label"] for s in state["sources"]] == ["runbook.md, Jam"]
    assert state["answer"] != prompts.FALLBACK


def test_far_retrieval_is_out_of_scope_without_calling_the_grader():
    llm = FakeLLM("1")
    app, seen = make_app(llm, [FAR], max_retries=1)
    state = ask(app, "best sourdough recipe?")
    assert state["answer"] == prompts.FALLBACK and len(seen) == 2
    assert not any(c.startswith("You are checking") for c in llm.calls)
    assert any("out of scope" in t for t in state["trace"])


def test_weak_retrieval_rewrites_then_falls_back():
    llm = FakeLLM("NONE")
    app, seen = make_app(llm, [FAR], max_retries=2)
    state = ask(app, "how do I bake bread")
    assert state["answer"] == prompts.FALLBACK
    assert state["retries"] == 2
    assert len(seen) == 3  # first attempt + two rewrites
    assert "fallback" in state["trace"]


def test_empty_question_goes_to_fallback():
    app, seen = make_app(FakeLLM(), [DOC])
    state = ask(app, "   ")
    assert state["answer"] == prompts.FALLBACK and seen == []


def test_unparsable_grade_keeps_docs():
    app, _ = make_app(FakeLLM("yes, all of them"), [DOC])
    assert "[1] runbook.md" in ask(app, "printer jam")["answer"]


def test_grader_cannot_veto_the_top_ranked_chunk():
    docs = [
        Document(page_content=f"chunk {n}", metadata={"source": f"doc{n}.md", "section": "S"}) for n in (1, 2, 3)
    ]
    app, _ = make_app(FakeLLM("3"), docs)  # grader only likes chunk 3
    state = ask(app, "printer jam")
    assert [s["label"] for s in state["sources"]] == ["doc1.md, S", "doc3.md, S"]
    assert "grade: kept 2/3" in state["trace"]


STEPS = Document(
    page_content="1. Open the cover and remove the paper.\n2. Reload the roll.\n3. Run a test print.",
    metadata={"source": "runbook.md", "section": "Paper jam", "distance": 0.4, "device_model": "HX-POS-200"},
)


def test_fast_path_shows_the_manuals_own_steps_with_no_model_call():
    llm = FakeLLM("NONE")
    app, _ = make_app(llm, [STEPS])
    state = ask(app, "printer paper jam")
    assert llm.calls == []  # neither the relevance check nor the writing step ran
    assert state["fast"] is True
    assert [b["text"] for b in state["blocks"] if b["kind"] == "step"][0] == "Open the cover and remove the paper."
    assert all(b["supported"] for b in state["blocks"] if b["kind"] == "step")
    assert state["strength"]["level"] == "strong"
    assert any(t.startswith("fast_answer: 3 step(s)") for t in state["trace"])


def test_fast_path_can_be_switched_off():
    llm = FakeLLM("1")
    app = build_graph(llm, lambda q, d: [STEPS], ErrorCodeDB(), fast_path=False)
    state = ask(app, "printer paper jam")
    assert not state.get("fast") and len(llm.calls) >= 1


def test_a_strong_match_skips_the_relevance_model_but_still_writes_the_answer():
    prose = Document(page_content="Blank receipts mean the paper is upside down.", metadata={"source": "r.md", "distance": 0.5})
    llm = FakeLLM("NONE")
    app, _ = make_app(llm, [prose])
    state = ask(app, "receipts blank")
    assert not any(c.startswith("You are checking") for c in llm.calls)
    assert any(c.startswith("You are a support assistant") for c in llm.calls)
    assert any("grade: skipped (strong match)" in t for t in state["trace"])


def test_a_strong_match_keeps_the_sibling_sections_of_the_same_document():
    def chunk(source, section, distance, text):
        return Document(page_content=text, metadata={"source": source, "section": section, "distance": distance})

    docs = [
        chunk("display.md", "Symptom", 0.26, "The display flickers."),
        chunk("display.md", "Fix", 0.48, "Reseat the cable."),  # further away, but the actual answer
        chunk("other.md", "Unrelated", 0.50, "Something else."),  # also far, from another document
    ]
    app, _ = make_app(FakeLLM("NONE"), docs)
    state = ask(app, "the customer display flickers")
    assert [s["label"] for s in state["sources"]] == ["display.md, Symptom", "display.md, Fix"]


def test_device_is_inferred_and_used_for_the_search():
    seen = []

    def retrieve_fn(query, device):
        seen.append(device)
        return [STEPS]

    app = build_graph(FakeLLM("1"), retrieve_fn, ErrorCodeDB(), known_devices_fn=lambda: ["HX-ATM-500", "HX-POS-200"])
    state = ask(app, "the ATM is jamming")
    assert state["inferred_device"] == "HX-ATM-500" and seen == ["HX-ATM-500"]
    seen.clear()
    ask(app, "the ATM is jamming", "HX-POS-200")  # an explicit choice is never overridden
    assert seen == ["HX-POS-200"]
    seen.clear()
    state = app.invoke({"question": "the ATM is jamming", "device_model": "all", "infer_device": False})
    assert seen == ["all"] and not state["inferred_device"]  # "search all devices" turns the guess off


def test_critical_error_code_raises_an_alert_from_the_real_policy_file():
    app, _ = make_app(FakeLLM("1"), [NEAR])
    state = ask(app, "ATM shows A-2002", "HX-ATM-500")
    assert state["intent"] == "error_code"
    alerts = {a["id"]: a for a in state["alerts"]}
    assert alerts["code-A-2002"]["level"] == "critical"
    assert "escalate" in alerts["code-A-2002"]["message"].lower()
    assert state["alerts"][0]["level"] == "critical"  # most severe first


def test_policy_runs_on_the_not_found_path_too():
    app, _ = make_app(FakeLLM("NONE"), [FAR], max_retries=0)
    state = ask(app, "I think there is a skimmer on the card slot")
    assert state["answer"] == prompts.FALLBACK
    assert [a["id"] for a in state["alerts"]] == ["tampering"]


def test_policy_function_is_injectable():
    seen = {}

    def fake_policy(question, records, text):
        seen.update(question=question, text=text)
        return [{"id": "x", "level": "warning", "title": "T", "message": "M"}]

    app = build_graph(FakeLLM("1"), lambda q, d: [DOC], ErrorCodeDB(), policy_fn=fake_policy)
    state = ask(app, "printer jam")
    assert state["alerts"][0]["id"] == "x"
    assert seen["question"] == "printer jam" and "Open the cover" in seen["text"]


def test_a_question_nowhere_near_any_document_skips_the_rewrite_entirely():
    way_off = Document(page_content="x", metadata={"source": "o.md", "distance": config.RELEVANCE_MAX_DISTANCE + 0.4})
    llm = FakeLLM("1")
    app, seen = make_app(llm, [way_off], max_retries=2)
    state = ask(app, "what is the capital of France")
    assert state["answer"] == prompts.FALLBACK
    assert len(seen) == 1 and not any(c.startswith("Rewrite this") for c in llm.calls)  # no pointless retries


def test_a_rewritten_query_must_match_more_closely_than_the_original():
    """Stops the model rewriting an unrelated question into something that merely sits near a document."""
    borderline = config.RELEVANCE_MAX_DISTANCE - 0.02  # passes the normal bar, fails the stricter retry bar
    first = Document(page_content="x", metadata={"source": "o.md", "distance": config.RELEVANCE_MAX_DISTANCE + 0.05})
    retry = Document(page_content="Open the cover.", metadata={"source": "o.md", "section": "S", "distance": borderline})
    answers = iter([[first], [retry], [retry]])
    app = build_graph(FakeLLM("1"), lambda q, d: next(answers), ErrorCodeDB(), max_retries=2)
    state = ask(app, "change the wifi password on my home router")
    assert state["answer"] == prompts.FALLBACK
    assert any("out of scope" in t for t in state["trace"][-4:])

    answers = iter([[Document(page_content="Open the cover.", metadata={"source": "o.md", "section": "S", "distance": borderline})]])
    app = build_graph(FakeLLM("1"), lambda q, d: next(answers), ErrorCodeDB(), max_retries=2)
    assert ask(app, "paper jam")["answer"] != prompts.FALLBACK  # the same distance is fine on a first try


def test_no_docs_retrieved_triggers_rewrite_then_fallback():
    app, seen = make_app(FakeLLM(), [], max_retries=1)
    state = ask(app, "printer jam", config.ALL_DEVICES)
    assert state["answer"] == prompts.FALLBACK and len(seen) == 2
