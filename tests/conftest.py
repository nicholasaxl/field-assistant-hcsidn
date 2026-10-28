"""Fixtures shared by the API-level tests: a client wired to a fake model, fake embeddings and a throwaway database."""
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

import config
from src import api as api_module
from src.error_lookup import ErrorCodeDB
from src.feedback import FeedbackStore
from src.graph import build_graph
from src.retriever import retrieve


class ScriptedLLM:
    def invoke(self, prompt):
        if prompt.startswith("You are checking"):
            return "1"
        if prompt.startswith("Rewrite this"):
            return "printer jam"
        return "1. Open the cover and remove the paper.\n2. Reboot the mainframe."


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = Chroma(
        collection_name=f"api_{uuid.uuid4().hex}", embedding_function=DeterministicFakeEmbedding(size=32)
    )
    code_db = ErrorCodeDB()
    graph = build_graph(ScriptedLLM(), lambda q, device: retrieve(q, store, device), code_db)
    monkeypatch.setattr(api_module, "get_resources", lambda: (store, code_db, graph))
    monkeypatch.setattr(config, "MANUALS_DIR", tmp_path / "manuals")
    monkeypatch.setattr(config, "RELEVANCE_MAX_DISTANCE", 100.0)  # fake embeddings have no real geometry
    feedback = FeedbackStore(":memory:")  # never touch the real data/feedback.db from tests
    monkeypatch.setattr(api_module, "get_feedback_store", lambda: feedback)
    test_client = TestClient(api_module.api)
    test_client.feedback = feedback
    test_client.registry = api_module.get_registry()
    return test_client


@pytest.fixture
def registry(_never_touch_real_models_or_keys):
    return _never_touch_real_models_or_keys
