"""Accuracy scorecard over tests/eval_questions.json. Measures the packaged sample library, not live use.

    python -m src.evaluate                 fast retrieval-only check (needs Ollama for embeddings)
    python -m src.evaluate --answers       end to end with the real model, ~10 minutes; writes docs/scorecard.*
    python -m src.evaluate --library       use your real library instead of the sample corpus

Retrieval-only mode never calls the chat model, so it is quick enough to run after every change.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable

import config
from src import prompts
from src.error_lookup import ErrorCodeDB
from src.policy import evaluate as evaluate_policy

QUESTIONS = config.ROOT / "tests" / "eval_questions.json"
DEMO_DIR = config.DATA_DIR / "upload_demo"


def load_cases(path: Path = QUESTIONS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 3) if total else None


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


# ---------- retrieval-only scoring (no chat model) ----------
def score_retrieval(
    cases: dict,
    retrieve_fn: Callable[[str, str], list],
    code_db: ErrorCodeDB,
    gate: float = config.RELEVANCE_MAX_DISTANCE,
    k: int = config.TOP_K,
) -> dict:
    """retrieve_fn(question, device) returns Documents (best first) with metadata['distance']."""
    details = []
    top_k_hits = top1_hits = 0
    for case in cases["in_scope"]:
        docs = retrieve_fn(case["question"], case["device_model"])[:k]
        expected = set(_as_list(case["expected_source"]))
        sources = [d.metadata.get("source") for d in docs]
        in_top_k = bool(expected & set(sources))
        top1 = bool(sources) and sources[0] in expected
        top_k_hits += in_top_k
        top1_hits += top1
        details.append({"kind": "in_scope", "question": case["question"], "ok": in_top_k, "top1": top1, "got": sources[:k]})

    refused = 0
    for case in cases["out_of_scope"]:
        docs = retrieve_fn(case["question"], "all")
        best = min((d.metadata["distance"] for d in docs), default=float("inf"))
        ok = best > gate
        refused += ok
        details.append({"kind": "out_of_scope", "question": case["question"], "ok": ok, "best_distance": round(best, 3)})

    alerted = 0
    for case in cases["critical"]:
        records = code_db.find(case["question"], case["device_model"])
        ids = {a["id"] for a in evaluate_policy(case["question"], records, "")}
        ok = case["expect_alert"] in ids
        alerted += ok
        details.append({"kind": "critical", "question": case["question"], "ok": ok, "alerts": sorted(ids)})

    coded = 0
    for case in cases["error_codes"]:
        found = {r["code"] for r in code_db.find(case["question"], case["device_model"])}
        ok = case["expect_code"] in found
        coded += ok
        details.append({"kind": "error_code", "question": case["question"], "ok": ok})

    return {
        "retrieval_hit_rate": _rate(top_k_hits, len(cases["in_scope"])),
        "retrieval_top1_rate": _rate(top1_hits, len(cases["in_scope"])),
        "refusal_rate": _rate(refused, len(cases["out_of_scope"])),
        "alert_rate": _rate(alerted, len(cases["critical"])),
        "error_code_rate": _rate(coded, len(cases["error_codes"])),
        "details": details,
    }


# ---------- end-to-end scoring (real model) ----------
def _doc_names(state: dict) -> set[str]:
    return {s["label"].split(",")[0].strip() for s in state.get("sources", [])}


def score_answers(cases: dict, ask_fn: Callable[[str, str], dict]) -> dict:
    """ask_fn(question, device) returns the final agent state, including 'elapsed'."""
    details, seconds = [], []
    passed = steps_total = steps_traced = 0
    for case in cases["in_scope"]:
        try:
            state = ask_fn(case["question"], case["device_model"])
        except Exception as exc:  # one failing question must not sink the run
            details.append({"kind": "in_scope", "question": case["question"], "ok": False, "error": str(exc)})
            continue
        seconds.append(state["elapsed"])
        blocks = [b for b in state.get("blocks", []) if b["kind"] == "step"]
        steps_total += len(blocks)
        steps_traced += sum(1 for b in blocks if b["supported"])
        text = " ".join(b["text"] for b in state.get("blocks", [])).lower()
        answered = state.get("answer") != prompts.FALLBACK
        source_ok = bool(set(_as_list(case["expected_source"])) & _doc_names(state))
        phrase_ok = any(p in text for p in case["expect_any"])
        ok = answered and source_ok and phrase_ok
        passed += ok
        details.append(
            {
                "kind": "in_scope",
                "question": case["question"],
                "ok": ok,
                "answered": answered,
                "source_ok": source_ok,
                "phrase_ok": phrase_ok,
                "seconds": round(state["elapsed"], 1),
            }
        )

    refused = 0
    for case in cases["out_of_scope"]:
        try:
            state = ask_fn(case["question"], "all")
        except Exception as exc:
            details.append({"kind": "out_of_scope", "question": case["question"], "ok": False, "error": str(exc)})
            continue
        seconds.append(state["elapsed"])
        ok = state.get("answer") == prompts.FALLBACK
        refused += ok
        details.append({"kind": "out_of_scope", "question": case["question"], "ok": ok})

    alerted = 0
    for case in cases["critical"]:
        try:
            state = ask_fn(case["question"], case["device_model"])
        except Exception as exc:
            details.append({"kind": "critical", "question": case["question"], "ok": False, "error": str(exc)})
            continue
        seconds.append(state["elapsed"])
        ids = {a["id"] for a in state.get("alerts", [])}
        ok = case["expect_alert"] in ids
        alerted += ok
        details.append({"kind": "critical", "question": case["question"], "ok": ok, "alerts": sorted(ids)})

    coded = 0
    for case in cases["error_codes"]:
        try:
            state = ask_fn(case["question"], case["device_model"])
        except Exception as exc:
            details.append({"kind": "error_code", "question": case["question"], "ok": False, "error": str(exc)})
            continue
        seconds.append(state["elapsed"])
        ok = any(
            s["kind"] == "error_code" and case["expect_code"] in s["label"] for s in state.get("sources", [])
        )
        coded += ok
        details.append({"kind": "error_code", "question": case["question"], "ok": ok})

    return {
        "answer_pass_rate": _rate(passed, len(cases["in_scope"])),
        "refusal_rate": _rate(refused, len(cases["out_of_scope"])),
        "alert_rate": _rate(alerted, len(cases["critical"])),
        "error_code_rate": _rate(coded, len(cases["error_codes"])),
        "traced_rate": _rate(steps_traced, steps_total),
        "median_seconds": round(statistics.median(seconds), 1) if seconds else None,
        "details": details,
    }


# ---------- reporting ----------
def render_markdown(result: dict) -> str:
    def pct(value):
        return "n/a" if value is None else f"{round(value * 100)}%"

    q = result["questions"]
    lines = [
        "# Accuracy scorecard",
        "",
        f"Run on {result['date']} with `{result['model']}` and `{result['embed_model']}`.",
        f"Corpus: {result['corpus']['documents']} documents, {result['corpus']['chunks']} passages "
        f"(the packaged sample library, not live use).",
        f"Questions: {q['in_scope']} in scope, {q['out_of_scope']} unrelated, {q['critical']} safety, {q['error_codes']} error codes.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Answers that pass (right document, right content, not refused) | {pct(result['answer_pass_rate'])} |",
        f"| Right document in the top {config.TOP_K} passages | {pct(result['retrieval_hit_rate'])} |",
        f"| Right document ranked first | {pct(result['retrieval_top1_rate'])} |",
        f"| Unrelated questions refused | {pct(result['refusal_rate'])} |",
        f"| Steps traced to a source | {pct(result['traced_rate'])} |",
        f"| Safety alerts raised when required | {pct(result['alert_rate'])} |",
        f"| Error codes matched exactly | {pct(result['error_code_rate'])} |",
        f"| Median time to answer | {'n/a' if result['median_seconds'] is None else str(result['median_seconds']) + ' s'} |",
        "",
    ]
    failures = [d for d in result["details"] if not d.get("ok")]
    if failures:
        lines += ["## Questions that failed", ""]
        for d in failures:
            lines.append(f"- ({d['kind']}) {d['question']}" + (f" - error: {d['error']}" if d.get("error") else ""))
    else:
        lines.append("No question failed in this run.")
    lines += [
        "",
        "Small test set: treat these as a regression guard and a rough indicator, not a guarantee. "
        "Re-run after changing documents, settings or code.",
    ]
    return "\n".join(lines) + "\n"


def build_corpus_store(directory: str):
    """A throwaway index of the sample documents so results don't depend on what's in the live library."""
    from src.ingest import get_store, ingest_directory, ingest_file
    from src.loader import iter_supported_files

    store = get_store(persist_dir=directory)
    ingest_directory(config.MANUALS_DIR, store)
    tags = json.loads((DEMO_DIR / "devices.json").read_text(encoding="utf-8")) if (DEMO_DIR / "devices.json").exists() else {}
    for path in iter_supported_files(DEMO_DIR):
        ingest_file(path, store, tags.get(path.name, config.ALL_DEVICES))
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description="Accuracy scorecard for the packaged sample library.")
    parser.add_argument("--answers", action="store_true", help="end to end with the real model (slow); writes docs/scorecard.*")
    parser.add_argument("--library", action="store_true", help="use your live library instead of the sample corpus")
    args = parser.parse_args()

    from src.graph import ask, build_graph, make_llm
    from src.ingest import get_store
    from src.retriever import retrieve

    cases = load_cases()
    code_db = ErrorCodeDB()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = get_store() if args.library else build_corpus_store(tmp)
        retrieve_fn = lambda q, device: retrieve(q, store, device)  # noqa: E731
        chunks = len(store.get()["ids"])
        documents = len({m["source"] for m in store.get(include=["metadatas"])["metadatas"]})

        result = score_retrieval(cases, retrieve_fn, code_db)
        result.update(answer_pass_rate=None, traced_rate=None, median_seconds=None)
        if args.answers:
            app = build_graph(make_llm(), retrieve_fn, code_db)
            answers = score_answers(cases, lambda q, device: ask(app, q, device))
            # In full mode the end-to-end numbers win where both modes measure the same thing.
            for key in ("refusal_rate", "alert_rate", "error_code_rate"):
                result[key] = answers[key]
            result.update(
                answer_pass_rate=answers["answer_pass_rate"],
                traced_rate=answers["traced_rate"],
                median_seconds=answers["median_seconds"],
            )
            result["details"] = answers["details"]

    result.update(
        date=date.today().isoformat(),
        model=config.CHAT_MODEL,
        embed_model=config.EMBED_MODEL,
        corpus={"documents": documents, "chunks": chunks},
        questions={k: len(cases[k]) for k in ("in_scope", "out_of_scope", "critical", "error_codes")},
    )

    for d in result["details"]:
        if not d.get("ok"):
            print(f"FAIL ({d['kind']}) {d['question']}")
    print(render_markdown(result))

    if args.answers and not args.library:
        config.DOCS_DIR.mkdir(exist_ok=True)
        (config.DOCS_DIR / "scorecard.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (config.DOCS_DIR / "scorecard.md").write_text(render_markdown(result), encoding="utf-8")
        print(f"Wrote {config.DOCS_DIR / 'scorecard.md'}")


if __name__ == "__main__":
    main()
