from langchain_core.documents import Document

import config
from src import evaluate as ev
from src import prompts
from src.error_lookup import ErrorCodeDB

CASES = {
    "in_scope": [
        {"question": "jam", "device_model": "all", "expected_source": ["a.md"], "expect_any": ["cover"]},
        {"question": "blank", "device_model": "all", "expected_source": ["b.md"], "expect_any": ["flip"]},
    ],
    "error_codes": [{"question": "P-1002 please", "device_model": "HX-POS-200", "expect_code": "P-1002"}],
    "out_of_scope": [{"question": "bread"}, {"question": "football"}],
    "critical": [{"question": "A-2002 shown", "device_model": "HX-ATM-500", "expect_alert": "code-A-2002"}],
}


def docs(*pairs):
    return [Document(page_content="x", metadata={"source": s, "distance": d}) for s, d in pairs]


def test_score_retrieval_counts_top_k_top1_refusals_alerts_and_codes():
    results = {
        "jam": docs(("a.md", 0.5), ("c.md", 0.6)),  # right doc first
        "blank": docs(("c.md", 0.5), ("b.md", 0.6)),  # right doc second: a top-k hit but not top-1
        "bread": docs(("a.md", 0.99)),  # too far: correctly refused
        "football": docs(("a.md", 0.4)),  # suspiciously close: NOT refused
    }
    score = ev.score_retrieval(CASES, lambda q, d: results[q], ErrorCodeDB(), gate=0.88, k=4)
    assert score["retrieval_hit_rate"] == 1.0 and score["retrieval_top1_rate"] == 0.5
    assert score["refusal_rate"] == 0.5
    assert score["alert_rate"] == 1.0 and score["error_code_rate"] == 1.0
    assert [d["question"] for d in score["details"] if not d["ok"]] == ["football"]


def fake_state(text, sources=("a.md, Jam",), steps=1, supported=True, alerts=(), answer=None, kind="document"):
    return {
        "answer": answer if answer is not None else text,
        "blocks": [{"kind": "step", "text": text, "cites": [1], "supported": supported}] * steps,
        "sources": [{"label": s, "text": "", "kind": kind} for s in sources],
        "alerts": [{"id": a} for a in alerts],
        "elapsed": 10.0,
    }


def test_keyword_only_matches_without_a_distance_do_not_break_scoring():
    keyword_only = [Document(page_content="x", metadata={"source": "a.md"})]  # found by BM25 alone
    results = {"jam": docs(("a.md", 0.5)), "blank": docs(("b.md", 0.5)), "bread": keyword_only, "football": keyword_only}
    score = ev.score_retrieval(CASES, lambda q, d: results[q], ErrorCodeDB())
    assert score["refusal_rate"] == 1.0  # no vector distance means no evidence the question is answerable


def test_score_answers_pass_traced_refusal_alert_and_code():
    def ask_fn(question, device):
        return {
            "jam": fake_state("Open the cover.", steps=2),
            "blank": fake_state("Reboot.", sources=("b.md, X",), supported=False),  # right doc, wrong content
            "bread": fake_state("", answer=prompts.FALLBACK, sources=()),
            "football": fake_state("A football answer.", sources=("a.md, Jam",)),  # should have refused
            "A-2002 shown": fake_state("Stop.", alerts=("code-A-2002",)),
            "P-1002 please": fake_state("Fix.", sources=("Error code P-1002 (HX-POS-200)",), kind="error_code"),
        }[question]

    score = ev.score_answers(CASES, ask_fn)
    assert score["answer_pass_rate"] == 0.5  # jam passes; blank fails on content
    assert score["refusal_rate"] == 0.5
    assert score["alert_rate"] == 1.0 and score["error_code_rate"] == 1.0
    assert score["traced_rate"] == round(2 / 3, 3)  # 3 steps asked in the in-scope answers, 2 traced
    assert score["median_seconds"] == 10.0


def test_one_crashing_question_is_recorded_not_fatal():
    def ask_fn(question, device):
        if question == "jam":
            raise ConnectionError("Ollama is down")
        return fake_state("Flip the roll.", sources=("b.md, X",))

    score = ev.score_answers({**CASES, "out_of_scope": [], "critical": [], "error_codes": []}, ask_fn)
    assert score["answer_pass_rate"] == 0.5
    assert any(d.get("error") == "Ollama is down" for d in score["details"])


def test_render_markdown_lists_failures_and_caveat():
    result = {
        "date": "2026-10-28", "model": "m", "embed_model": "e", "corpus": {"documents": 7, "chunks": 40},
        "questions": {"in_scope": 2, "out_of_scope": 2, "critical": 1, "error_codes": 1},
        "answer_pass_rate": 0.5, "retrieval_hit_rate": 1.0, "retrieval_top1_rate": 0.5, "refusal_rate": 0.5,
        "traced_rate": None, "alert_rate": 1.0, "error_code_rate": 1.0, "median_seconds": 10.0,
        "details": [{"kind": "out_of_scope", "question": "football", "ok": False}],
    }
    text = ev.render_markdown(result)
    assert "| Answers that pass" in text and "50%" in text and "n/a" in text
    assert "- (out_of_scope) football" in text and "regression guard" in text


def test_shipped_question_file_is_consistent_with_the_shipped_documents():
    cases = ev.load_cases()
    known = {p.name for p in config.MANUALS_DIR.iterdir()} | {p.name for p in ev.DEMO_DIR.iterdir()}
    assert len(cases["in_scope"]) >= 15 and len(cases["out_of_scope"]) >= 5 and len(cases["critical"]) >= 4
    for case in cases["in_scope"]:
        assert set(ev._as_list(case["expected_source"])) <= known, case["question"]
        assert case["expect_any"] and all(p == p.lower() for p in case["expect_any"])
    codes = ErrorCodeDB()
    for case in cases["error_codes"]:
        assert codes.find(case["question"], case["device_model"]), case["question"]
    tags = ev.json.loads((ev.DEMO_DIR / "devices.json").read_text(encoding="utf-8"))
    assert set(tags) <= known
