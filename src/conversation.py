"""Shallow conversation memory, decided by rules rather than the small model.

Only the last few turns are kept (question, device, what was suggested) so a follow-up such as "that didn't
work" or "what about the kiosk?" can be turned into a standalone search. Rules are used because a 3B model
rewrites questions unreliably and each call would add several seconds.
"""
from __future__ import annotations

import re

import config
from src.textutil import tokenize

MAX_HISTORY = 3
_CODE = re.compile(r"\b[A-Za-z]{1,3}-?\d{3,5}\b")
FAIL_CUES = re.compile(
    r"\b(didn'?t work|doesn'?t work|did not work|does not work|not working|still|same (error|problem|issue)|"
    r"failed|no luck|nothing happened|no change|tried (that|it|everything))\b",
    re.I,
)
FOLLOW_CUES = re.compile(
    r"^(and|but|so|then|what if|what about|how long|why|how many|where|which|is it|can i|do i|should i)\b|"
    r"\b(that|it|this|those|them|step \d+|the (first|second|third|last|next) step)\b",
    re.I,
)
ESCALATION_HINT = "escalate if the problem persists, replace the part"
VAGUE_MAX_TOKENS = 1


def is_follow_up(question: str, history: list[dict]) -> bool:
    if not history:
        return False
    text = question.strip()
    if _CODE.search(text):
        return False  # a new error code starts a new problem
    if FAIL_CUES.search(text):
        return True
    tokens = tokenize(text)
    if len(tokens) > 9:
        return False  # long enough to stand on its own
    # Without a cue, only a genuinely tiny question ("kiosk?") leans on the last turn. Judged on the words typed,
    # not the keywords left after stop-words, or "how do i clean my toilet" would borrow the previous question.
    return bool(FOLLOW_CUES.search(text)) or (len(tokens) <= 2 and len(text.split()) <= 3)


def contextualize(question: str, history: list[dict]) -> dict | None:
    """The standalone question and what to avoid repeating, or None when the question stands on its own."""
    history = history[-MAX_HISTORY:]
    if not is_follow_up(question, history):
        return None
    last = history[-1]
    failure = bool(FAIL_CUES.search(question))
    base = last["question"].rstrip(" ?.!")
    standalone = f"{base}. {question.strip()}"
    if failure:
        standalone += f" {ESCALATION_HINT}"
    return {
        "question": standalone,
        "failure": failure,
        # Passages already shown for a failed procedure are not offered a second time.
        "exclude": list(last.get("sources", [])) if failure else [],
        "device": last.get("device"),
    }


def is_vague(question: str) -> bool:
    """Too little to search on ("help", "broken") and no error code."""
    return not _CODE.search(question) and len(tokenize(question)) <= VAGUE_MAX_TOKENS


def tied_devices(
    docs: list,
    margin: float = config.CLARIFY_MARGIN,
    weak_after: float = config.CLARIFY_WEAK,
    answerable_below: float = config.RELEVANCE_MAX_DISTANCE,
) -> list[str]:
    """Device models whose best passages are nearly equally close, but only when no passage is a strong match.

    Two or more means the question could be about either device, so it is better to ask than to guess.
    A question that isn't answerable at all is never turned into a device question: it is simply refused.
    """
    best: dict[str, float] = {}
    for doc in docs:
        model = doc.metadata.get("device_model")
        distance = doc.metadata.get("distance")
        if model and model != config.ALL_DEVICES and distance is not None:
            best[model] = min(distance, best.get(model, distance))
    if len(best) < 2:
        return []
    ordered = sorted(best.items(), key=lambda item: item[1])
    if ordered[0][1] <= weak_after:
        return []  # a clearly strong match: just answer
    if ordered[0][1] > answerable_below:
        return []  # nothing is close enough to answer; the out-of-scope refusal handles it
    return [m for m, d in ordered if d - ordered[0][1] <= margin][:4] if len(
        [1 for _, d in ordered if d - ordered[0][1] <= margin]
    ) >= 2 else []
