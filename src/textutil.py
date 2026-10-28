"""Small text helpers shared by ingestion, retrieval and the agent."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    "the a an and or to of in on at for with from is are be it its this that then if when you your as by "
    "not do does into out up how what why can i my me we our".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase search tokens. Hyphenated ids (HX-A500-PICK, P-1002) also yield their parts and the joined form."""
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        parts = re.split(r"[-.]", raw)
        if len(parts) > 1:
            tokens.append(raw)
            tokens.append("".join(parts))
            tokens.extend(p for p in parts if p)
        else:
            tokens.append(raw)
    return [t for t in tokens if t not in STOPWORDS]


def pretty_title(source: str) -> str:
    """'atm_cash_dispenser_jam_runbook.md' -> 'atm cash dispenser jam runbook'."""
    return re.sub(r"[_]+", " ", re.sub(r"\.[a-z0-9]{2,5}$", "", source, flags=re.I)).strip()


def chunk_header(meta: dict) -> str:
    """Context prepended to a chunk before it is embedded: device | document | section or page.

    The header is searchable but never shown to the user (the original text is kept in metadata['body']).
    """
    device = meta.get("device_model", "all")
    place = f"page {meta['page']}" if "page" in meta else meta.get("section", "")
    parts = ["all devices" if device == "all" else device, pretty_title(meta.get("source", "")), place]
    return " | ".join(p for p in parts if p)


def body_text(doc) -> str:
    """The text a person should read: the original chunk without the search header."""
    return doc.metadata.get("body", doc.page_content)
