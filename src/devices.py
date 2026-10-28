"""Work out which device a question is about when the engineer left the selector on "All devices"."""
from __future__ import annotations

import re

_KIND_WORDS = {
    "atm": re.compile(r"\batms?\b|\bcash machine\b", re.I),
    "pos": re.compile(r"\bpos\b|\bpoint of sale\b", re.I),
    "kiosk": re.compile(r"\bkiosks?\b", re.I),
}


def kind_of(model: str) -> str | None:
    upper = model.upper()
    for kind in ("ATM", "POS", "KIOSK"):
        if kind in upper:
            return kind.lower()
    return None


def infer_device(question: str, code_records: list[dict], known_models: list[str]) -> str | None:
    """A device only when the evidence points at exactly one; otherwise None and nothing is assumed.

    1. An exact error code that exists for a single device.
    2. The question says ATM / POS / kiosk, and exactly one known model is of that kind.
    """
    code_devices = {r["device_model"] for r in code_records}
    if len(code_devices) == 1:
        return next(iter(code_devices))
    kinds = {kind for kind, pattern in _KIND_WORDS.items() if pattern.search(question)}
    if len(kinds) != 1:
        return None
    matches = [m for m in known_models if kind_of(m) == next(iter(kinds))]
    return matches[0] if len(matches) == 1 else None
