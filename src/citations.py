"""Attach [n] citations to answer steps by checking which source actually contains the step's wording.

Small local models copy citation examples and invent source numbers, so the model's own markers are
stripped and recomputed here. A step that matches no source is left uncited and counted, so the UI
can warn the engineer to verify it.
"""
from __future__ import annotations

import re

import config

_STEP =re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
_MODEL_CITATION = re.compile(r"\s*\[\d+\]")
_STOPWORDS = frozenset(
    "the a an and or to of in on at for with from is are be it its this that then if when you your "
    "as by not do does into out up".split()
)
MATCH_THRESHOLD = 0.6  # share of a step's content words found in a source
MAX_CITATIONS = 2
SECONDARY_MARGIN = 0.15  # extra sources must score within this of the best match


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _step_citations(step_text: str, source_words: list[set[str]]) -> list[int]:
    """1-based numbers of the sources that contain this step, best first."""
    step_words = _words(step_text)
    if not step_words:
        return []
    scored = sorted(
        ((len(step_words & words) / len(step_words), number) for number, words in enumerate(source_words, 1)),
        key=lambda pair: (-pair[0], pair[1]),
    )
    # A second citation must be nearly as strong as the best one, so a few shared common
    # words in an unrelated passage don't produce a bogus extra source.
    cutoff = max(MATCH_THRESHOLD, scored[0][0] - SECONDARY_MARGIN) if scored else MATCH_THRESHOLD
    return [number for score, number in scored[:MAX_CITATIONS] if score >= cutoff]


def answer_strength(sources: list[dict], matched: int, unmatched: int, has_exact_code: bool) -> dict:
    """A coarse trust label for the UI. Deliberately words, never a probability."""
    if unmatched:
        return {"level": "check", "label": "Check the sources", "reason": f"{unmatched} step(s) not found in the documents"}
    if matched == 0:
        return {"level": "check", "label": "Check the sources", "reason": "No steps could be traced to a document"}
    distances = [s["distance"] for s in sources if s.get("distance") is not None]
    if has_exact_code or (distances and min(distances) <= config.STRONG_DISTANCE):
        return {"level": "strong", "label": "Strong match", "reason": "Every step traces to a close source"}
    return {"level": "good", "label": "Good match", "reason": "Every step traces to a source"}


def attribute(answer: str, source_texts: list[str]) -> tuple[str, int, int]:
    """Return (answer with [n] added to supported steps, matched steps, unmatched steps)."""
    source_words = [_words(text) for text in source_texts]
    lines, matched, unmatched = [], 0, 0
    for line in _MODEL_CITATION.sub("", answer).splitlines():
        if not _STEP.match(line):
            lines.append(line)
            continue
        hits = _step_citations(_STEP.sub("", line, count=1), source_words)
        if hits:
            lines.append(line.rstrip() + " " + " ".join(f"[{n}]" for n in hits))
            matched += 1
        else:
            lines.append(line)
            unmatched += 1
    return "\n".join(lines), matched, unmatched


def analyze(answer: str, source_texts: list[str]) -> list[dict]:
    """The same attribution as structured blocks for a UI.

    Each block is {"kind": "step" | "text", "text", "cites": [n, ...], "supported": bool | None}.
    Blank lines are dropped and list markers are removed from step text.
    """
    source_words = [_words(text) for text in source_texts]
    blocks = []
    for line in _MODEL_CITATION.sub("", answer).splitlines():
        if not line.strip():
            continue
        if not _STEP.match(line):
            blocks.append({"kind": "text", "text": line.strip(), "cites": [], "supported": None})
            continue
        text = _STEP.sub("", line, count=1).strip()
        cites = _step_citations(text, source_words)
        blocks.append({"kind": "step", "text": text, "cites": cites, "supported": bool(cites)})
    return blocks
