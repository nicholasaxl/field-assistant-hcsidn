"""Search: vector similarity fused with keyword (BM25) matching, narrowed by device model.

Vector search finds passages that mean the same thing; keyword search finds exact terms such as part numbers
and error codes. They are merged with reciprocal rank fusion. The best vector hit is always kept, because its
distance is what decides whether a question is answerable at all.
"""
from __future__ import annotations

import math
from collections import Counter

from langchain_chroma import Chroma
from langchain_core.documents import Document

import config
from src.glossary import expand_query
from src.textutil import tokenize

RRF_K = 60
POOL = 8  # candidates taken from each search before fusion


class BM25:
    """Okapi BM25 over a small in-memory corpus."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokens = [tokenize(t) for t in texts]
        self.lengths = [len(t) for t in self.tokens]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for toks in self.tokens:
            df.update(set(toks))
        n = len(self.tokens)
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        self.tf = [Counter(toks) for toks in self.tokens]

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        out = []
        for tf, length in zip(self.tf, self.lengths):
            score = 0.0
            for term in terms:
                f = tf.get(term)
                if f:
                    norm = self.k1 * (1 - self.b + self.b * length / (self.avg or 1))
                    score += self.idf[term] * f * (self.k1 + 1) / (f + norm)
            out.append(score)
        return out


# One keyword index per library state. The key changes whenever a document is added, removed or replaced.
_indexes: dict[tuple, tuple[BM25, list[str], list[dict], list[str]]] = {}


def _keyword_index(store: Chroma):
    ids = store.get(include=[])["ids"]
    key = (id(store), len(ids), hash(tuple(sorted(ids))))
    if key not in _indexes:
        _indexes.clear()  # only the current library state is worth keeping
        found = store.get(include=["documents", "metadatas"])
        _indexes[key] = (BM25(found["documents"]), found["ids"], found["metadatas"], found["documents"])
    return _indexes[key]


def _restore(doc: Document) -> Document:
    """Show the original text, not the search header it was embedded with."""
    body = doc.metadata.get("body")
    if body is not None:
        doc.page_content = body
    return doc


def _allowed(meta: dict, device_model: str | None) -> bool:
    if not device_model or device_model == config.ALL_DEVICES:
        return True
    return meta.get("device_model") in (device_model, config.ALL_DEVICES)


def retrieve(
    question: str,
    store: Chroma,
    device_model: str | None = None,
    k: int = config.TOP_K,
    hybrid: bool | None = None,
    groups: list[list[str]] | None = None,
) -> list[Document]:
    """Top-k chunks, best first. A device filter also keeps chunks tagged for all devices.

    Every chunk carries `metadata["distance"]` when the vector search found it (lower is closer). Chunks found
    only by keyword carry none, so they can never make an unrelated question look answerable.
    """
    hybrid = config.HYBRID_SEARCH if hybrid is None else hybrid
    query, _added = expand_query(question, groups)

    where = None
    if device_model and device_model != config.ALL_DEVICES:
        where = {"device_model": {"$in": [device_model, config.ALL_DEVICES]}}

    vector_hits = []
    for doc, distance in store.similarity_search_with_score(query, k=POOL if hybrid else k, filter=where):
        doc.metadata["distance"] = float(distance)
        vector_hits.append(doc)
    if not hybrid:
        return [_restore(d) for d in vector_hits[:k]]

    # Keyword side, restricted to the same device scope.
    bm25, ids, metas, texts = _keyword_index(store)
    scores = bm25.scores(query)
    ranked = sorted(
        (i for i in range(len(ids)) if scores[i] > 0 and _allowed(metas[i], device_model)),
        key=lambda i: -scores[i],
    )[:POOL]

    fused: dict[str, float] = {}
    by_id: dict[str, Document] = {}
    for rank, doc in enumerate(vector_hits):
        key = _key(doc.metadata, doc.page_content)
        fused[key] = fused.get(key, 0.0) + 1 / (RRF_K + rank + 1)
        by_id[key] = doc
    for rank, i in enumerate(ranked):
        key = _key(metas[i], texts[i])
        fused[key] = fused.get(key, 0.0) + 1 / (RRF_K + rank + 1)
        by_id.setdefault(key, Document(page_content=texts[i], metadata=dict(metas[i])))

    order = sorted(fused, key=lambda key: -fused[key])[:k]
    if vector_hits:
        best = _key(vector_hits[0].metadata, vector_hits[0].page_content)
        if best not in order:
            order[-1] = best  # the best vector hit decides answerability; never drop it
    return [_restore(by_id[key]) for key in order]


def _key(meta: dict, text: str) -> str:
    """Identity of a chunk across the two searches: the same stored text from the same file."""
    return f"{meta.get('source')}|{meta.get('file_hash')}|{hash(text)}"
