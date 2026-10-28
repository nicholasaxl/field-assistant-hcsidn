"""Customer-editable synonyms (data/glossary.json) used to widen a search, never to change what the user sees."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import config


@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> list[list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8")).get("groups", [])


def load_groups(path: str | Path | None = None) -> list[list[str]]:
    path = Path(path or config.GLOSSARY_JSON)
    if not path.exists():
        return []
    return _read(str(path), path.stat().st_mtime)  # re-read when the file is edited


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase.lower())}\b", text) is not None


def expand_query(question: str, groups: list[list[str]] | None = None) -> tuple[str, list[str]]:
    """Return (search query, phrases added). Groups whose phrase appears in the question add their siblings."""
    groups = load_groups() if groups is None else groups
    lowered = question.lower()
    added: list[str] = []
    for group in groups:
        if any(_has(lowered, phrase) for phrase in group):
            added.extend(p for p in group if not _has(lowered, p) and p not in added)
    added = added[:6]  # keep the original question dominant
    return (f"{question} {' '.join(added)}".strip() if added else question), added
