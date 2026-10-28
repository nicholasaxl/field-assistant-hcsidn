"""Similarity search with an optional device-model filter."""
from __future__ import annotations

from langchain_chroma import Chroma
from langchain_core.documents import Document

import config


def retrieve(
    question: str,
    store: Chroma,
    device_model: str | None = None,
    k: int = config.TOP_K,
) -> list[Document]:
    """Top-k chunks, best first. A device filter also keeps chunks tagged for all devices.

    Each returned chunk carries `metadata["distance"]` (lower is closer) so the agent can tell
    "found something relevant" from "nothing in the documents matches".
    """
    where = None
    if device_model and device_model != config.ALL_DEVICES:
        where = {"device_model": {"$in": [device_model, config.ALL_DEVICES]}}
    docs = []
    for doc, distance in store.similarity_search_with_score(question, k=k, filter=where):
        doc.metadata["distance"] = float(distance)
        docs.append(doc)
    return docs
