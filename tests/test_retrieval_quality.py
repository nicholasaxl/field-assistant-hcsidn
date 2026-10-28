import uuid

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

import config
from src.devices import infer_device
from src.fastpath import numbered_steps, pick_fast_steps
from src.glossary import expand_query, load_groups
from src.ingest import _chunk, ingest_directory, ingest_file, migrate_index, stale_sources
from src.retriever import BM25, retrieve
from src.textutil import body_text, chunk_header, tokenize


@pytest.fixture
def store():
    return Chroma(collection_name=f"q_{uuid.uuid4().hex}", embedding_function=DeterministicFakeEmbedding(size=32))


def write(path, title, text, model="HX-POS-200"):
    path.write_text(f"---\ndevice_model: {model}\n---\n# {title}\n{text}\n", encoding="utf-8")


# ---------- text helpers ----------
def test_tokenize_keeps_ids_whole_and_in_parts():
    tokens = tokenize("Replace HX-A500-PICK for error P-1002 in the cassette")
    assert {"hx-a500-pick", "hxa500pick", "a500", "pick", "p-1002", "p1002"} <= set(tokens)
    assert "the" not in tokens and "in" not in tokens


def test_chunk_header_names_device_document_and_place():
    meta = {"device_model": "HX-ATM-500", "source": "atm_cash_runbook.md", "section": "Clearing a note jam (A-1001)"}
    assert chunk_header(meta) == "HX-ATM-500 | atm cash runbook | Clearing a note jam (A-1001)"
    assert chunk_header({"device_model": "all", "source": "net.pdf", "page": 3}) == "all devices | net | page 3"


# ---------- BM25 ----------
def test_bm25_ranks_the_exact_term_first_and_ignores_unrelated():
    bm25 = BM25(["pick roller kit HX-A500-PICK twelve months", "receipt paper roll", "network gateway ping"])
    scores = bm25.scores("part number HX-A500-PICK")
    assert scores[0] > 0 and scores[1] == 0 and scores[2] == 0
    assert BM25([]).scores("anything") == []


# ---------- ingestion format ----------
def test_chunks_are_embedded_with_a_header_but_store_the_original_text(store, tmp_path):
    write(tmp_path / "pos_runbook.md", "Paper jam (P-1002)", "1. Open the cover.\n2. Remove the paper.")
    ingest_file(tmp_path / "pos_runbook.md", store)
    stored = store.get(include=["documents", "metadatas"])
    assert stored["documents"][0].startswith("HX-POS-200 | pos runbook | Paper jam (P-1002)\n")
    assert stored["metadatas"][0]["body"].startswith("1. Open the cover.")
    assert stored["metadatas"][0]["index_version"] == config.INDEX_VERSION

    doc = retrieve("paper jam", store, "HX-POS-200", k=1)[0]
    assert doc.page_content == body_text(doc) and not doc.page_content.startswith("HX-POS-200 |")


def test_a_table_stays_in_one_chunk_but_long_prose_still_splits():
    table = Document(page_content="Slot | Cassette\n" + "1 | C1\n" * 100, metadata={"section": "Table 1", "source": "x.docx"})
    prose = Document(page_content="word " * 600, metadata={"section": "Intro", "source": "x.docx"})
    chunks = _chunk([table, prose])
    assert sum(1 for c in chunks if c.metadata["section"] == "Table 1") == 1
    assert sum(1 for c in chunks if c.metadata["section"] == "Intro") > 1


def test_documents_in_an_older_format_are_reindexed_from_their_files(store, tmp_path):
    write(tmp_path / "a.md", "Jam", "1. Open.\n2. Close.")
    ingest_directory(tmp_path, store)
    assert stale_sources(store) == {}
    stored = store.get(include=["metadatas"])
    store._collection.update(  # pretend it was indexed by the previous version
        ids=stored["ids"], metadatas=[{**m, "index_version": 1} for m in stored["metadatas"]]
    )
    assert stale_sources(store) == {"a.md": "HX-POS-200"}
    assert [r.status for r in migrate_index(store, tmp_path)] == ["updated"]
    assert stale_sources(store) == {}
    assert migrate_index(store, tmp_path) == []  # nothing left to do


# ---------- hybrid retrieval ----------
def test_keyword_search_finds_an_exact_part_number_that_vectors_cannot(store, tmp_path):
    for i in range(6):
        write(tmp_path / f"filler{i}.md", f"Topic {i}", f"General text number {i} about nothing in particular.")
    write(tmp_path / "parts.md", "Parts", "Pick roller kit part number HX-A500-PICK replace every 12 months.")
    ingest_directory(tmp_path, store)
    hybrid = retrieve("HX-A500-PICK", store, "all", k=3, hybrid=True)
    assert "parts.md" in [d.metadata["source"] for d in hybrid]
    found = next(d for d in hybrid if d.metadata["source"] == "parts.md")
    assert found.page_content.startswith("Pick roller kit")  # original text, not the header


def test_the_best_vector_hit_is_never_dropped_and_keyword_only_hits_have_no_distance(store, tmp_path):
    for i in range(5):
        write(tmp_path / f"d{i}.md", f"T{i}", f"text {i}")
    write(tmp_path / "kw.md", "Parts", "HX-A500-PICK")
    ingest_directory(tmp_path, store)
    vector_best = retrieve("HX-A500-PICK", store, "all", k=1, hybrid=False)[0]
    hybrid = retrieve("HX-A500-PICK", store, "all", k=1, hybrid=True)
    assert len(hybrid) == 1
    assert hybrid[0].metadata["distance"] == vector_best.metadata["distance"]  # the answerability gate is unaffected
    wide = retrieve("HX-A500-PICK", store, "all", k=6, hybrid=True)
    assert all(("distance" in d.metadata) or d.metadata["source"] == "kw.md" for d in wide)


def test_device_filter_applies_to_keyword_hits_too(store, tmp_path):
    write(tmp_path / "pos.md", "Parts", "Roller HX-A500-PICK", "HX-POS-200")
    write(tmp_path / "atm.md", "Parts", "Roller HX-A500-PICK", "HX-ATM-500")
    ingest_directory(tmp_path, store)
    sources = {d.metadata["source"] for d in retrieve("HX-A500-PICK", store, "HX-POS-200", k=6, hybrid=True)}
    assert sources == {"pos.md"}


# ---------- glossary ----------
def test_glossary_adds_siblings_only_when_a_phrase_matches_a_whole_word():
    groups = [["note jam", "cash jam", "bill jam"], ["pin pad", "keypad"]]
    query, added = expand_query("How do I clear a note jam?", groups)
    assert added == ["cash jam", "bill jam"] and query.startswith("How do I clear a note jam?")
    assert expand_query("unrelated question", groups) == ("unrelated question", [])
    assert expand_query("the keypads are dirty", groups)[1] == []  # 'keypad' only as a whole word


def test_shipped_glossary_loads_and_missing_file_means_no_expansion(tmp_path):
    assert any("note jam" in g for g in load_groups())
    assert load_groups(tmp_path / "nope.json") == []


# ---------- device inference ----------
def test_device_inferred_from_a_single_code_or_a_single_model_of_that_kind():
    models = ["HX-ATM-500", "HX-KIOSK-300", "HX-POS-200"]
    assert infer_device("anything", [{"device_model": "HX-POS-200"}], models) == "HX-POS-200"
    assert infer_device("The ATM is jammed", [], models) == "HX-ATM-500"
    assert infer_device("kiosk screen is black", [], models) == "HX-KIOSK-300"
    assert infer_device("POS and ATM both fail", [], models) is None  # two kinds: don't guess
    assert infer_device("The ATM is jammed", [], ["HX-ATM-500", "HX-ATM-600"]) is None  # two ATM models
    assert infer_device("printer is jammed", [], models) is None


# ---------- fast path ----------
def test_numbered_steps_needs_a_complete_list_starting_at_one():
    assert numbered_steps("1. Open.\n2. Close.\nNote text") == ["Open.", "Close."]
    assert numbered_steps("3. Third.\n4. Fourth.") == []  # chunk started mid-list
    assert numbered_steps("1. Only one.") == []
    assert numbered_steps("1. A.\n3. C.") == []  # gap in numbering


def passage(text, distance, section="Paper jam (P-1002)"):
    return Document(page_content=text, metadata={"source": "r.md", "section": section, "distance": distance})


def test_fast_path_picks_a_close_numbered_procedure_and_refuses_otherwise():
    steps = "1. Open the cover.\n2. Remove the paper."
    doc, got = pick_fast_steps("printer paper jam", [passage(steps, 0.4)], [], 0.6)
    assert doc is not None and got == ["Open the cover.", "Remove the paper."]
    assert pick_fast_steps("printer paper jam", [passage(steps, 0.7)], [], 0.6)[0] is None  # too far
    assert pick_fast_steps("sourdough bread recipe", [passage(steps, 0.4)], [], 0.6)[0] is None  # no shared words
    assert pick_fast_steps("printer paper jam", [passage("Just prose here.", 0.4)], [], 0.6)[0] is None
    assert pick_fast_steps("printer paper jam", [Document(page_content=steps, metadata={})], [], 0.6)[0] is None


def test_fast_path_for_an_error_code_uses_the_passage_that_names_the_code():
    other = passage("1. Flip the roll.\n2. Retry.", 0.45, section="Faint or blank receipts")
    named = passage("1. Open the cover.\n2. Remove the paper.", 0.7, section="Paper jam (P-1001, P-1002)")
    doc, steps = pick_fast_steps("P-1002", [other, named], [{"code": "P-1002"}], 0.6)
    assert doc is named and steps[0] == "Open the cover."  # looser distance is fine once the code is named
    assert pick_fast_steps("P-1002", [other], [{"code": "P-1002"}], 0.6)[0] is None  # never answer from the wrong section
