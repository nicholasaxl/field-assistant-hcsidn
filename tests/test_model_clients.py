import config
from src.graph import make_llm
from src.ingest import get_embeddings


def test_real_model_clients_accept_the_configured_settings():
    """Construction needs no network; it catches settings the Ollama clients reject (e.g. keep_alive type)."""
    assert get_embeddings().keep_alive == config.KEEP_ALIVE
    llm = make_llm()
    assert llm.keep_alive == config.KEEP_ALIVE
    assert llm.model == config.CHAT_MODEL
