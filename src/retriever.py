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
    """Top-k chunks. A device filter also keeps chunks tagged for all devices."""
    where = None
    if device_model and device_model != config.ALL_DEVICES:
        where = {"device_model": {"$in": [device_model, config.ALL_DEVICES]}}
    return store.similarity_search(question, k=k, filter=where)
