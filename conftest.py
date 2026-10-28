# Presence of this file puts the project root on sys.path so tests can `import config` and `import src`.
import pytest


class MemoryKeyring:
    """A stand-in for the operating system credential store, so no test touches the real one."""

    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.items.get((service, name))

    def set_password(self, service, name, value):
        self.items[(service, name)] = value

    def delete_password(self, service, name):
        self.items.pop((service, name), None)


class FakeChat:
    """Records what it was asked and answers like a model would."""

    def __init__(self, model="fake", key=None, provider=None, base_url=None):
        self.model, self.key, self.provider, self.base_url, self.calls = model, key, provider, base_url, []

    def invoke(self, prompt):
        self.calls.append(prompt)
        return "OK"


@pytest.fixture(autouse=True)
def _never_touch_real_models_or_keys(tmp_path, monkeypatch):
    """Model choice and API keys live outside the project; a test must never read or write the real ones."""
    import config
    from src import api
    from src.models import ModelRegistry, SecretStore

    monkeypatch.setattr(config, "MODEL_SETTINGS_JSON", tmp_path / "model_settings.json")
    registry = ModelRegistry(
        secrets=SecretStore(backend=MemoryKeyring(), environ={}),
        settings_path=tmp_path / "model_settings.json",
        local_factory=lambda model: FakeChat(model),
        online_factory=lambda provider, model, key, base_url: FakeChat(model, key, provider, base_url),
        ollama_models_fn=lambda: ["qwen2.5:3b", "llama3.2:3b"],
        policies_fn=lambda: {"allow_online_models": True},
        remote_models_fn=lambda provider, key, base_url: ["gpt-4o-mini", "gpt-4o"],
    )
    api.get_registry.cache_clear()
    monkeypatch.setattr(api, "get_registry", lambda: registry)
    yield registry


@pytest.fixture(autouse=True)
def _never_touch_the_real_feedback_db(tmp_path, monkeypatch):
    """Point the feedback store at a throwaway file so no test can write to data/feedback.db."""
    import config
    from src import api

    monkeypatch.setattr(config, "FEEDBACK_DB", tmp_path / "guard-feedback.db")
    api.get_feedback_store.cache_clear()
    api.answer_cache.clear()  # a saved answer from one test must never answer another
    yield
    api.answer_cache.clear()
    # A test may have replaced the function with a plain lambda; only the cached original has cache_clear.
    getattr(api.get_feedback_store, "cache_clear", lambda: None)()
