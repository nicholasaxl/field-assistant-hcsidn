"""Ingestion: loader -> split -> embed -> persist to Chroma. Idempotent per file (by content hash).

Each chunk is embedded together with a short header (device | document | section) so the search model knows
where a passage comes from, for example which error code a section covers. The original text is kept in
metadata['body'] and is what people and the agent read.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from src.loader import iter_supported_files, load_file
from src.textutil import chunk_header

TABLE_MAX_CHARS = 1500  # a table up to this size stays in one piece so its rows keep their headings


@dataclass
class IngestResult:
    source: str
    status: str  # added | updated | skipped | error
    chunks: int = 0
    message: str = ""


def get_embeddings():
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=config.EMBED_MODEL, base_url=config.OLLAMA_BASE_URL, keep_alive=config.KEEP_ALIVE
    )


def get_store(embeddings=None, persist_dir: str | Path | None = None) -> Chroma:
    return Chroma(
        collection_name=config.COLLECTION,
        embedding_function=embeddings or get_embeddings(),
        persist_directory=str(persist_dir or config.VECTOR_DIR),
    )


def _existing(store: Chroma, source: str) -> tuple[list[str], list[dict]]:
    found = store.get(where={"source": source}, include=["metadatas"])
    return found["ids"], found["metadatas"]


def _is_whole_table(doc) -> bool:
    return str(doc.metadata.get("section", "")).startswith("Table ") and len(doc.page_content) <= TABLE_MAX_CHARS


def _chunk(docs: list) -> list:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
    )
    chunks = []
    for doc in docs:
        chunks.extend([doc] if _is_whole_table(doc) else splitter.split_documents([doc]))
    for chunk in chunks:
        body = chunk.page_content
        chunk.metadata["body"] = body
        chunk.metadata["index_version"] = config.INDEX_VERSION
        chunk.page_content = f"{chunk_header(chunk.metadata)}\n{body}"
    return chunks


def ingest_file(path: str | Path, store: Chroma, device_model: str = config.ALL_DEVICES) -> IngestResult:
    path = Path(path)
    docs = load_file(path, device_model)
    digest = docs[0].metadata["file_hash"]
    new_models = {d.metadata["device_model"] for d in docs}

    old_ids, old_meta = _existing(store, path.name)
    if old_ids:
        same_hash = {m.get("file_hash") for m in old_meta} == {digest}
        same_models = {m.get("device_model") for m in old_meta} == new_models
        same_format = {m.get("index_version") for m in old_meta} == {config.INDEX_VERSION}
        if same_hash and same_models and same_format:
            return IngestResult(path.name, "skipped", len(old_ids), "unchanged")
        store.delete(ids=old_ids)

    chunks = _chunk(docs)
    ids = [f"{path.name}:{digest[:10]}:{i}" for i in range(len(chunks))]
    store.add_documents(chunks, ids=ids)
    return IngestResult(path.name, "updated" if old_ids else "added", len(chunks))


def ingest_directory(
    directory: str | Path, store: Chroma, device_model: str = config.ALL_DEVICES
) -> list[IngestResult]:
    results = []
    for path in iter_supported_files(directory):
        try:
            results.append(ingest_file(path, store, device_model))
        except Exception as exc:  # one bad file must not stop the batch
            results.append(IngestResult(path.name, "error", message=str(exc)))
    return results


def stale_sources(store: Chroma) -> dict[str, str]:
    """Documents indexed in an older chunk format, mapped to the device they were tagged with."""
    metas = store.get(include=["metadatas"])["metadatas"]
    return {
        m["source"]: m.get("device_model", config.ALL_DEVICES)
        for m in metas
        if m.get("index_version") != config.INDEX_VERSION
    }


def migrate_index(store: Chroma, directory: str | Path | None = None) -> list[IngestResult]:
    """Re-index stale documents from their saved files. A document whose file is gone stays as it was."""
    directory = Path(directory or config.MANUALS_DIR)
    results = []
    for source, device in stale_sources(store).items():
        path = directory / source
        if not path.exists():
            continue
        try:
            results.append(ingest_file(path, store, device))
        except Exception as exc:
            results.append(IngestResult(source, "error", message=str(exc)))
    return results


def delete_document(source: str, store: Chroma) -> int:
    ids, _ = _existing(store, source)
    if ids:
        store.delete(ids=ids)
    return len(ids)


def list_documents(store: Chroma) -> list[dict]:
    found = store.get(include=["metadatas"])
    grouped: dict[str, dict] = defaultdict(lambda: {"chunks": 0})
    for meta in found["metadatas"]:
        entry = grouped[meta["source"]]
        entry["chunks"] += 1
        entry["type"] = meta.get("doc_type", "")
        entry["device_model"] = meta.get("device_model", config.ALL_DEVICES)
    return [{"source": name, **info} for name, info in sorted(grouped.items())]


def main() -> None:
    parser = argparse.ArgumentParser(description="Index documents into the local vector store.")
    parser.add_argument("--dir", default=str(config.MANUALS_DIR), help="folder to scan")
    parser.add_argument("--device-model", default=config.ALL_DEVICES, help="default device tag")
    parser.add_argument("--reindex", action="store_true", help="re-index documents stored in an older format")
    args = parser.parse_args()

    store = get_store()
    if args.reindex:
        results = migrate_index(store)
        print(f"Re-indexed {sum(r.status != 'error' for r in results)} document(s)")
        for result in results:
            if result.status == "error":
                print(f"error    {result.source}: {result.message}")
    else:
        for result in ingest_directory(args.dir, store, args.device_model):
            detail = f" ({result.message})" if result.message else ""
            print(f"{result.status:8} {result.source}  chunks={result.chunks}{detail}")
    print(f"Total chunks in store: {len(store.get()['ids'])}")


if __name__ == "__main__":
    main()
