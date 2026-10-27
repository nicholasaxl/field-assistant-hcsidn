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
    assert state["trace"][-2] == "generate"
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
    assert state["trace"][-1] == "citations: 1 step(s) matched, 1 unmatched"


def test_weak_retrieval_rewrites_then_falls_back():
    llm = FakeLLM("NONE")
    app, seen = make_app(llm, [DOC], max_retries=2)
    state = ask(app, "how do I bake bread")
    assert state["answer"] == prompts.FALLBACK
    assert state["retries"] == 2
    assert len(seen) == 3  # first attempt + two rewrites
    assert state["trace"][-1] == "fallback"


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


def test_no_docs_retrieved_triggers_rewrite_then_fallback():
    app, seen = make_app(FakeLLM(), [], max_retries=1)
    state = ask(app, "printer jam", config.ALL_DEVICES)
    assert state["answer"] == prompts.FALLBACK and len(seen) == 2
