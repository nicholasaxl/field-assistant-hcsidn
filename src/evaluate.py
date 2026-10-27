"""Retrieval hit-rate check against tests/eval_questions.json. Needs Ollama running with the embedding model.

Usage: python -m src.evaluate
"""
from __future__ import annotations

import json

import config
from src.ingest import get_store
from src.retriever import retrieve

QUESTIONS = config.ROOT / "tests" / "eval_questions.json"


def main() -> None:
    store = get_store()
    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    hits = 0
    for case in cases:
        docs = retrieve(case["question"], store, case.get("device_model"))
        found = case["expected_source"] in {d.metadata.get("source") for d in docs}
        hits += found
        print(f"{'HIT ' if found else 'MISS'} {case['question']}")
    print(f"\nRetrieval hit rate: {hits}/{len(cases)} ({100 * hits / len(cases):.0f}%)")


if __name__ == "__main__":
    main()
