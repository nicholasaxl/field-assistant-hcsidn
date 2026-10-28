# Presence of this file puts the project root on sys.path so tests can `import config` and `import src`.
import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_real_feedback_db(tmp_path, monkeypatch):
    """Point the feedback store at a throwaway file so no test can write to data/feedback.db."""
    import config
    from src import api

    monkeypatch.setattr(config, "FEEDBACK_DB", tmp_path / "guard-feedback.db")
    api.get_feedback_store.cache_clear()
    yield
    # A test may have replaced the function with a plain lambda; only the cached original has cache_clear.
    getattr(api.get_feedback_store, "cache_clear", lambda: None)()
