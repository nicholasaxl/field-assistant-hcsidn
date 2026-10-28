import json
import sqlite3
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

import config
from src import api as api_module
from src.feedback import FeedbackStore
from src.models import ANTHROPIC_MODELS, AnthropicChat, ModelError, ModelRegistry, SecretStore, SwitchableLLM

KEY = "sk-ant-test-0123456789abcdefghijklmnop"


# ---------- a fake Anthropic client ----------
def reply(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


TEXT = lambda t: SimpleNamespace(type="text", text=t)  # noqa: E731
THINKING = SimpleNamespace(type="thinking", thinking="")


class FakeAnthropic:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.messages = SimpleNamespace(create=self._create("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))

    def _create(self, route):
        def create(**kwargs):
            self.calls.append((route, kwargs))
            if self._error:
                raise self._error
            return self._response

        return create


def status_error(cls, code, message="boom"):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(code, request=request, json={"error": {"type": "x", "message": message}})
    return cls(message, response=response, body=response.json())


# ---------- SecretStore ----------
def test_a_key_is_saved_read_hinted_and_deleted(registry):
    store = registry.secrets
    assert store.get("anthropic") == (None, None)
    store.set("anthropic", f"  {KEY}\n")
    assert store.get("anthropic") == (KEY, "store")
    status = store.status("anthropic")
    assert status == {"saved": True, "source": "store", "hint": "…mnop", "can_store": True, "env_var": "ANTHROPIC_API_KEY"}
    assert KEY not in json.dumps(status)
    store.delete("anthropic")
    store.delete("anthropic")  # deleting twice is harmless
    assert store.get("anthropic") == (None, None)


def test_an_environment_variable_wins_over_the_stored_key(registry):
    store = SecretStore(backend=registry.secrets.backend, environ={"ANTHROPIC_API_KEY": "sk-ant-from-the-environment-0000"})
    store.set("anthropic", KEY)
    assert store.get("anthropic") == ("sk-ant-from-the-environment-0000", "env")
    assert store.status("anthropic")["source"] == "env"


@pytest.mark.parametrize("bad", ["", "short", "has a space in the middle of a long key 123456", "x" * 10])
def test_obviously_wrong_keys_are_rejected_without_echoing_them(registry, bad):
    with pytest.raises(ModelError) as caught:
        registry.secrets.set("anthropic", bad)
    assert bad.strip() == "" or bad not in str(caught.value)


def test_no_secure_store_means_no_saving_and_a_pointer_to_the_environment_variable():
    class Backend:  # looks like keyring's "fail" backend
        def get_keyring(self):
            from keyring.backends import fail

            return fail.Keyring()

        def get_password(self, *a):
            return None

    store = SecretStore(backend=Backend(), environ={})
    assert store.can_store() is False and store.status("anthropic")["can_store"] is False
    with pytest.raises(ModelError, match="ANTHROPIC_API_KEY"):
        store.set("anthropic", KEY)


# ---------- the Claude adapter ----------
def test_only_the_text_blocks_are_returned_and_the_request_is_shaped_correctly():
    client = FakeAnthropic(reply(THINKING, TEXT("  1. Open the cover.  "), TEXT(" 2. Close it."), stop="end_turn"))
    answer = AnthropicChat("claude-opus-5-5", KEY, client=client).invoke("How?")
    assert answer == "1. Open the cover.   2. Close it."  # text blocks are joined as the model wrote them
    route, request = client.calls[0]
    assert route == "beta"  # Opus 5.5 / Sonnet 5.5 get the server-side refusal fallback
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == 4096
    assert request["output_config"] == {"effort": "low"} and request["messages"] == [{"role": "user", "content": "How?"}]
    assert "temperature" not in request and "thinking" not in request  # both are rejected or unnecessary on these models


def test_haiku_uses_the_plain_endpoint_because_it_has_no_server_side_fallback():
    client = FakeAnthropic(reply(TEXT("OK")))
    AnthropicChat("claude-haiku-5-5", KEY, client=client).invoke("ping")
    route, request = client.calls[0]
    assert route == "messages" and "fallbacks" not in request and "betas" not in request


def test_a_refusal_and_an_empty_answer_become_readable_errors():
    with pytest.raises(ModelError, match="safety systems declined"):
        AnthropicChat("claude-opus-5-5", KEY, client=FakeAnthropic(reply(TEXT("..."), stop="refusal"))).invoke("x")
    with pytest.raises(ModelError, match="ran out of room"):
        AnthropicChat("claude-opus-5-5", KEY, client=FakeAnthropic(reply(THINKING, stop="max_tokens"))).invoke("x")


@pytest.mark.parametrize(
    "error, expected",
    [
        (status_error(anthropic.AuthenticationError, 401), "rejected the API key"),
        (status_error(anthropic.PermissionDeniedError, 403), "isn't allowed to use that model"),
        (status_error(anthropic.NotFoundError, 404), "doesn't recognise the model"),
        (status_error(anthropic.RateLimitError, 429), "rate limit"),
        (status_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "credit balance is too low"),
        (status_error(anthropic.InternalServerError, 500), "busy or having problems"),
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com")), "too long"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "Can't reach Anthropic"),
    ],
)
def test_every_failure_becomes_a_plain_message_that_never_contains_the_key(error, expected):
    with pytest.raises(ModelError) as caught:
        AnthropicChat("claude-opus-5-5", KEY, client=FakeAnthropic(error=error)).invoke("x")
    assert expected.lower() in str(caught.value).lower()
    assert KEY not in str(caught.value) and caught.value.__cause__ is None  # no traceback chain to leak from


# ---------- the registry ----------
def test_by_default_the_local_model_from_config_is_active(registry):
    active = registry.active()
    assert active == {"provider": "ollama", "model": config.CHAT_MODEL, "label": config.CHAT_MODEL, "local": True,
                      "where": "This computer (Ollama)", "note": None}
    assert registry.active_id() == f"ollama:{config.CHAT_MODEL}"


def test_choosing_another_local_model_is_validated_and_saved_without_any_key(registry, tmp_path):
    assert registry.select("ollama", "llama3.2:3b")["model"] == "llama3.2:3b"
    assert json.loads((tmp_path / "model_settings.json").read_text()) == {"provider": "ollama", "model": "llama3.2:3b", "consent": False}
    with pytest.raises(ModelError, match="ollama pull"):
        registry.select("ollama", "not-installed:1b")


def test_going_online_needs_a_key_a_known_model_and_explicit_consent(registry, tmp_path):
    with pytest.raises(ModelError, match="Save an API key for Claude"):
        registry.select("anthropic", "claude-sonnet-5-5", consent=True)
    registry.secrets.set("anthropic", KEY)
    with pytest.raises(ModelError, match="Confirm"):
        registry.select("anthropic", "claude-sonnet-5-5", consent=False)
    with pytest.raises(ModelError, match="listed Claude models"):
        registry.select("anthropic", "gpt-whatever", consent=True)

    active = registry.select("anthropic", "claude-sonnet-5-5", consent=True)
    assert active["provider"] == "anthropic" and active["local"] is False and active["label"] == "Claude Sonnet 5.5"
    assert "online" in active["where"]
    assert KEY not in (tmp_path / "model_settings.json").read_text()  # the settings file never holds the key
    assert registry.select("ollama", "qwen2.5:3b")["local"] is True
    registry.secrets.set("anthropic", KEY)
    with pytest.raises(ModelError, match="Confirm"):  # switching away clears the consent
        registry.select("anthropic", "claude-sonnet-5-5", consent=False)


def test_the_agent_follows_the_switch_without_being_rebuilt(registry):
    llm = SwitchableLLM(registry)  # what the compiled graph holds
    llm.invoke("a")
    local = registry.llm()
    assert local.model == config.CHAT_MODEL and local.calls == ["a"]
    registry.secrets.set("anthropic", KEY)
    registry.select("anthropic", "claude-haiku-5-5", consent=True)
    llm.invoke("b")
    online = registry.llm()
    assert online is not local and online.model == "claude-haiku-5-5" and online.key == KEY and online.calls == ["b"]
    assert local.calls == ["a"]  # the local model heard nothing after the switch
    assert registry.llm() is online  # clients are reused, not rebuilt per question


def test_losing_the_key_or_a_company_lock_drops_back_to_local_and_says_why(registry):
    registry.secrets.set("anthropic", KEY)
    registry.select("anthropic", "claude-opus-5-5", consent=True)
    registry.secrets.delete("anthropic")
    active = registry.active()
    assert active["local"] is True and "No API key" in active["note"]

    registry.secrets.set("anthropic", KEY)
    assert registry.active()["local"] is False  # the saved choice returns with the key
    registry._policies = lambda: {"allow_online_models": False}
    locked = registry.active()
    assert locked["local"] is True and "policies.json" in locked["note"]
    with pytest.raises(ModelError, match="turned off"):
        registry.select("anthropic", "claude-opus-5-5", consent=True)
    assert registry.public()["providers"][1]["enabled"] is False


def test_the_connection_test_reports_success_and_each_kind_of_failure(registry):
    assert registry.test("ollama", "qwen2.5:3b")["ok"] is True
    assert registry.test("anthropic", "claude-opus-5-5") == {"ok": False, "message": "Save an API key for Claude first."}
    registry.secrets.set("anthropic", KEY)
    result = registry.test("anthropic", "claude-opus-5-5")
    assert result["ok"] is True and result["reply"] == "OK" and result["ms"] >= 0

    def refuse(provider, model, key, base_url):
        raise ModelError("Anthropic rejected the API key. Check it in Model settings.")

    registry._online_factory = refuse
    assert registry.test("anthropic", "claude-opus-5-5")["message"].startswith("Anthropic rejected")

    def down(model):
        raise ConnectionError("connection refused")

    registry._local_factory = down
    assert registry.test("ollama", "qwen2.5:3b")["message"] == "Can't reach Ollama. Start it, then try again."


def test_what_the_ui_receives_describes_everything_except_the_key(registry):
    registry.secrets.set("anthropic", KEY)
    public = registry.public()
    assert KEY not in json.dumps(public) and public["providers"][1]["key"]["hint"] == "…mnop"
    assert public["search"] == {"model": config.EMBED_MODEL, "where": "This computer (Ollama)", "local": True}
    assert [m["id"] for m in public["providers"][0]["models"]] == ["qwen2.5:3b", "llama3.2:3b"]
    assert [m["id"] for m in public["providers"][1]["models"]] == [m["id"] for m in ANTHROPIC_MODELS]
    assert "sent to Anthropic" in public["providers"][1]["note"]


# ---------- the HTTP API ----------
def test_saving_a_key_returns_a_hint_and_never_the_key(client):
    assert client.get("/api/models").json()["providers"][1]["key"]["saved"] is False
    saved = client.put("/api/models/key", json={"provider": "anthropic", "key": KEY})
    assert saved.status_code == 200 and saved.json()["key"]["hint"] == "…mnop" and KEY not in saved.text
    assert KEY not in client.get("/api/models").text
    assert client.registry.secrets.get("anthropic") == (KEY, "store")

    too_short = client.put("/api/models/key", json={"provider": "anthropic", "key": "short"})
    assert too_short.status_code == 400 and "short" not in too_short.json()["detail"].replace("doesn't look like", "")


def test_a_malformed_request_does_not_echo_the_key_back(client):
    response = client.put("/api/models/key", json={"provider": "not-a-provider", "key": KEY})
    assert response.status_code == 422 and KEY not in response.text


def test_choosing_an_online_model_through_the_api_and_returning_to_local(client):
    body = {"provider": "anthropic", "model": "claude-haiku-5-5", "consent": True}
    assert client.post("/api/models/select", json=body).status_code == 400  # no key yet
    client.put("/api/models/key", json={"provider": "anthropic", "key": KEY})
    assert client.post("/api/models/select", json={**body, "consent": False}).status_code == 400
    chosen = client.post("/api/models/select", json=body).json()["active"]
    assert chosen["label"] == "Claude Haiku 5.5" and chosen["local"] is False
    assert client.get("/api/models").json()["active"]["model"] == "claude-haiku-5-5"

    removed = client.delete("/api/models/key/anthropic").json()
    assert removed["key"]["saved"] is False and removed["active"]["local"] is True  # no key, so back on the local model
    # A different key saved later must not silently go online on the strength of the old confirmation.
    client.put("/api/models/key", json={"provider": "anthropic", "key": KEY.replace("test", "newer")})
    assert client.get("/api/models").json()["active"]["local"] is True
    assert client.post("/api/models/select", json={**body, "consent": False}).status_code == 400
    assert client.post("/api/models/test", json={"provider": "ollama", "model": "qwen2.5:3b"}).json()["ok"] is True


def test_settings_can_only_be_changed_from_the_computer_running_the_app(client):
    remote = TestClient(api_module.api, client=("203.0.113.9", 50000))
    assert remote.get("/api/models").status_code == 200  # reading is harmless
    for call in (
        lambda: remote.put("/api/models/key", json={"provider": "anthropic", "key": KEY}),
        lambda: remote.delete("/api/models/key/anthropic"),
        lambda: remote.post("/api/models/select", json={"provider": "ollama", "model": "qwen2.5:3b"}),
        lambda: remote.post("/api/models/test", json={"provider": "ollama", "model": "qwen2.5:3b"}),
    ):
        assert call().status_code == 403
    assert client.registry.secrets.get("anthropic") == (None, None)


def ask(client, question="printer jam", **extra):
    events = client.post("/api/ask", json={"question": question, "device_model": "all", **extra}).text
    return [json.loads(c[len("data: "):]) for c in events.split("\n\n") if c.startswith("data: ")][-1]


def test_every_model_written_answer_says_which_model_wrote_it(client):
    client.post("/api/documents", files=[("files", ("runbook.md", b"# Jam\nOpen the cover and remove the paper.\n", "text/markdown"))])
    final = ask(client)
    assert final["model"] == {"provider": "ollama", "model": config.CHAT_MODEL, "label": config.CHAT_MODEL, "local": True}
    assert client.feedback.get_interaction(final["interaction_id"])["model"] == config.CHAT_MODEL

    client.put("/api/models/key", json={"provider": "anthropic", "key": KEY})
    client.post("/api/models/select", json={"provider": "anthropic", "model": "claude-opus-5-5", "consent": True})
    online = ask(client)
    assert online["model"]["local"] is False and online["model"]["label"] == "Claude Opus 5.5"
    assert client.feedback.get_interaction(online["interaction_id"])["model"] == "claude-opus-5-5"


def test_an_answer_copied_from_the_manual_names_no_model(client, monkeypatch):
    monkeypatch.setattr(config, "FAST_PATH_DISTANCE", 100.0)  # fake embeddings have no real geometry
    text = b"# Printer jam\n1. Open the cover.\n2. Remove the paper.\n"
    client.post("/api/documents", files=[("files", ("jam.md", text, "text/markdown"))])
    final = ask(client, "printer jam open cover")
    assert final["fast"] is True and final["model"] is None


def test_a_saved_answer_is_never_served_after_the_model_changes(client):
    client.post("/api/documents", files=[("files", ("runbook.md", b"# Jam\nOpen the cover and remove the paper.\n", "text/markdown"))])
    assert ask(client)["cached"] is False
    assert ask(client)["cached"] is True
    client.post("/api/models/select", json={"provider": "ollama", "model": "llama3.2:3b"})
    assert ask(client)["cached"] is False  # a different model gets its own answer
    assert ask(client)["model"]["model"] == "llama3.2:3b"


# ---------- the feedback database ----------
def test_a_database_from_before_models_were_recorded_gains_the_column_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE interactions (id TEXT PRIMARY KEY, ts REAL NOT NULL, question TEXT NOT NULL, device TEXT NOT NULL,"
        " intent TEXT, fallback INTEGER NOT NULL DEFAULT 0, cached INTEGER NOT NULL DEFAULT 0, elapsed REAL, stages TEXT,"
        " steps TEXT, sources TEXT, codes TEXT, alerts TEXT, is_sample INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO interactions (id, ts, question, device) VALUES ('old1', 1.0, 'an old question', 'all');"
    )
    old.commit()
    old.close()

    store = FeedbackStore(path)
    assert store.get_interaction("old1")["model"] is None  # existing rows survive
    new = store.log_interaction(question="new", device="all", model="claude-haiku-5-5")
    assert store.get_interaction(new)["model"] == "claude-haiku-5-5"
    assert FeedbackStore(path).get_interaction(new)["model"] == "claude-haiku-5-5"  # reopening an upgraded file is fine
    assert store.export_csv().splitlines()[0].split(",")[-2:] == ["model", "sample_data"]
