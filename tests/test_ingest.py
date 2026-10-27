import uuid

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.ingest import delete_document, ingest_directory, ingest_file, list_documents
from src.retriever import retrieve


@pytest.fixture
def store():
    return Chroma(
        collection_name=f"test_{uuid.uuid4().hex}",
        embedding_function=DeterministicFakeEmbedding(size=32),
    )


def _write(path, text, model="HX-POS-200"):
    path.write_text(f"---\ndevice_model: {model}\n---\n# Section\n{text}\n", encoding="utf-8")
    return path


def test_ingest_is_idempotent_and_updates_on_change(store, tmp_path):
    path = _write(tmp_path / "a.md", "Replace the paper roll.")
    assert ingest_file(path, store).status == "added"
    assert ingest_file(path, store).status == "skipped"

    _write(path, "Replace the paper roll and clean the platen.")
    result = ingest_file(path, store)
    assert result.status == "updated"
    docs = list_documents(store)
    assert len(docs) == 1 and docs[0]["chunks"] == result.chunks


def test_delete_document(store, tmp_path):
    path = _write(tmp_path / "a.md", "text")
    ingest_file(path, store)
    assert delete_document("a.md", store) >= 1
    assert list_documents(store) == []
    assert delete_document("a.md", store) == 0


def test_device_filter_keeps_all_tagged_chunks(store, tmp_path):
    _write(tmp_path / "pos.md", "printer paper", "HX-POS-200")
    _write(tmp_path / "atm.md", "cash jam", "HX-ATM-500")
    _write(tmp_path / "net.md", "network checks", "all")
    ingest_directory(tmp_path, store)
    sources = {d.metadata["source"] for d in retrieve("anything", store, "HX-POS-200", k=10)}
    assert sources == {"pos.md", "net.md"}
    assert {d.metadata["source"] for d in retrieve("anything", store, None, k=10)} == {"pos.md", "atm.md", "net.md"}


def test_bad_file_does_not_stop_batch(store, tmp_path):
    _write(tmp_path / "good.md", "ok")
    (tmp_path / "blank.md").write_text("  ", encoding="utf-8")
    results = {r.source: r.status for r in ingest_directory(tmp_path, store)}
    assert results == {"blank.md": "error", "good.md": "added"}
