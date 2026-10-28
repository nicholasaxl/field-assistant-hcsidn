"""Fast path: when the best passage is a close match and holds a numbered procedure, show its steps verbatim.

This skips both model calls (relevance check and writing). Every step is the manual's own wording, so the
answer is instant and fully traceable. Anything less certain falls back to the normal model path.
"""
from __future__ import annotations

import re

from src.textutil import STOPWORDS, body_text, tokenize

_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(\S.*?)\s*$")
CODE_DISTANCE_SLACK = 0.25  # an explicit mention of the error code is strong evidence, so allow a looser distance
MAX_CODE_DISTANCE = 0.85


def numbered_steps(text: str) -> list[str]:
    """The steps of a complete numbered list that starts at 1; empty if the list is partial or missing."""
    steps: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = _NUMBERED.match(line)
        if match:
            steps.append((int(match.group(1)), match.group(2)))
    if len(steps) < 2 or steps[0][0] != 1:
        return []
    if [n for n, _ in steps] != list(range(1, len(steps) + 1)):
        return []
    return [text for _, text in steps]


def _shares_words(question: str, doc) -> bool:
    """At least one meaningful word of the question appears in the passage or its section title."""
    wanted = {t for t in tokenize(question) if t not in STOPWORDS and len(t) > 2}
    have = set(tokenize(f"{doc.metadata.get('section', '')} {body_text(doc)}"))
    return bool(wanted & have)


def pick_fast_steps(question: str, docs: list, code_records: list[dict], max_distance: float):
    """(document, steps) when the fast path is safe for this question, otherwise (None, [])."""
    if not docs:
        return None, []
    if code_records:
        codes = [r["code"].lower() for r in code_records]
        candidates = [
            d for d in docs if any(c in f"{d.metadata.get('section', '')} {body_text(d)}".lower() for c in codes)
        ]
        limit = min(max_distance + CODE_DISTANCE_SLACK, MAX_CODE_DISTANCE)
        need_overlap = False
    else:
        candidates, limit, need_overlap = docs[:1], max_distance, True

    for doc in candidates:
        distance = doc.metadata.get("distance")
        if distance is None or distance > limit:
            continue
        if need_overlap and not _shares_words(question, doc):
            continue
        steps = numbered_steps(body_text(doc))
        if steps:
            return doc, steps
    return None, []
