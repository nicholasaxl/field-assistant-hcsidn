"""OpenAI, Gemini and custom OpenAI-compatible services. Every call here goes to a fake client: no network."""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from src.models import ONLINE_PROVIDERS, ModelError, OpenAICompatibleChat, validate_base_url

KEY = "sk-test-0123456789abcdefghijklmnop"
GEMINI_KEY = "AIzaTest0123456789abcdefghijklmn"
CUSTOM_URL = "https://llm.example.com/v1"


def completion(text, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)])


class FakeOpenAI:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def status_error(cls, code, message="boom"):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(code, request=request, json={"error": {"message": message}})
    return cls(message, response=response, body=response.json())


def chat(client, who="OpenAI", model="gpt-4o-mini"):
    return OpenAICompatibleChat(who, model, KEY, "https://api.openai.com/v1", client=client)


# ---------- the adapter ----------
def test_only_the_model_and_the_prompt_are_sent():
    client = FakeOpenAI(completion("  1. Open the cover.  "))
    assert chat(client).invoke("How?") == "1. Open the cover."
    assert client.calls == [{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "How?"}]}]


def test_geminis_models_prefix_is_removed():
    client = FakeOpenAI(completion("OK"))
    chat(client, "Gemini", "models/gemini-2.0-flash").invoke("x")
    assert client.calls[0]["model"] == "gemini-2.0-flash"


@pytest.mark.parametrize(
    "response, expected",
    [
        (completion("..", finish="content_filter"), "safety filter"),
        (completion("", finish="length"), "ran out of room"),
        (completion(None), "empty answer"),
        (SimpleNamespace(choices=[]), "no answer"),
    ],
)
def test_an_unusable_reply_becomes_a_readable_error(response, expected):
    with pytest.raises(ModelError, match=expected):
        chat(FakeOpenAI(response)).invoke("x")


@pytest.mark.parametrize(
    "error, expected",
    [
        (status_error(openai.AuthenticationError, 401), "rejected the API key"),
        (status_error(openai.PermissionDeniedError, 403), "isn't allowed to use that model"),
        (status_error(openai.NotFoundError, 404), "doesn't recognise the model"),
        (status_error(openai.RateLimitError, 429), "quota"),
        (status_error(openai.BadRequestError, 400, "Unsupported parameter"), "Unsupported parameter"),
        (status_error(openai.InternalServerError, 500), "busy or having problems"),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")), "too long"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")), "Can't reach OpenAI"),
    ],
)
def test_every_failure_becomes_a_plain_message_that_never_contains_the_key(error, expected):
    with pytest.raises(ModelError) as caught:
        chat(FakeOpenAI(error=error)).invoke("x")
    assert expected.lower() in str(caught.value).lower()
    assert KEY not in str(caught.value) and caught.value.__cause__ is None


# ---------- custom addresses ----------
@pytest.mark.parametrize("url", ["https://llm.example.com/v1", "https://llm.example.com/v1/", "http://localhost:1234/v1"])
def test_acceptable_addresses_are_kept_without_a_trailing_slash(url):
    assert validate_base_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    ["", "llm.example.com", "ftp://llm.example.com", "http://llm.example.com/v1", "https://user:pw@llm.example.com",
     "https://llm.example.com/v1?key=abc", "https://llm.example.com/#x", "https://" + "a" * 400 + ".com"],
)
def test_unsafe_or_malformed_addresses_are_refused(url):
    with pytest.raises(ModelError):
        validate_base_url(url)


# ---------- the registry with several providers ----------
def test_each_provider_has_its_own_key_and_environment_variable(registry):
    assert [ONLINE_PROVIDERS[p].env_var for p in ("anthropic", "openai", "gemini", "custom")] == [
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "FIELD_ASSIST_CUSTOM_API_KEY"]
    registry.secrets.set("openai", KEY)
    assert registry.secrets.get("openai") == (KEY, "store") and registry.secrets.get("gemini") == (None, None)


def test_openai_and_gemini_use_their_fixed_addresses_and_free_text_model_names(registry):
    registry.secrets.set("openai", KEY)
    registry.secrets.set("gemini", GEMINI_KEY)
    with pytest.raises(ModelError, match="Enter a valid model name"):
        registry.select("openai", "not a model!", consent=True)
    with pytest.raises(ModelError, match="Confirm"):
        registry.select("openai", "gpt-4o-mini", consent=False)

    active = registry.select("openai", "gpt-4o-mini", consent=True)
    assert active["label"] == "OpenAI · gpt-4o-mini" and "OpenAI's servers" in active["where"]
    llm = registry.llm()
    assert (llm.provider, llm.model, llm.key, llm.base_url) == ("openai", "gpt-4o-mini", KEY, "https://api.openai.com/v1")

    registry.select("gemini", "gemini-2.0-flash", consent=True)
    llm = registry.llm()
    assert llm.provider == "gemini" and llm.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_a_custom_service_needs_a_valid_address_which_is_remembered(registry, tmp_path):
    registry.secrets.set("custom", KEY)
    with pytest.raises(ModelError, match="service's address"):
        registry.select("custom", "my-model", consent=True)
    with pytest.raises(ModelError, match="https://"):
        registry.select("custom", "my-model", consent=True, base_url="http://llm.example.com/v1")

    active = registry.select("custom", "my-model", consent=True, base_url=CUSTOM_URL + "/")
    assert active["label"] == "Custom · my-model" and "llm.example.com" in active["where"]
    assert registry.llm().base_url == CUSTOM_URL
    assert KEY not in (tmp_path / "model_settings.json").read_text()

    registry.select("ollama", "qwen2.5:3b")
    assert json.loads((tmp_path / "model_settings.json").read_text())["custom_base_url"] == CUSTOM_URL  # kept for next time
    public = registry.public()
    custom = next(p for p in public["providers"] if p["id"] == "custom")
    assert custom["needs_base_url"] is True and custom["base_url"] == CUSTOM_URL
    assert "the address you enter" in custom["note"]


def test_removing_one_providers_key_leaves_a_different_active_provider_alone(registry):
    registry.secrets.set("anthropic", KEY.replace("sk-", "sk-ant-"))
    registry.secrets.set("openai", KEY)
    registry.select("anthropic", "claude-haiku-5-5", consent=True)
    registry.secrets.delete("openai")
    registry.forget_online_choice("openai")
    assert registry.active()["provider"] == "anthropic"

    registry.secrets.delete("anthropic")
    registry.forget_online_choice("anthropic")
    registry.secrets.set("anthropic", KEY.replace("sk-", "sk-ant-"))
    assert registry.active()["local"] is True  # a new key starts from local until confirmed again


def test_switching_provider_needs_a_fresh_confirmation_each_time(registry):
    registry.secrets.set("openai", KEY)
    registry.secrets.set("gemini", GEMINI_KEY)
    registry.select("openai", "gpt-4o-mini", consent=True)
    with pytest.raises(ModelError, match="Confirm"):
        registry.select("gemini", "gemini-2.0-flash", consent=False)
    assert registry.active()["provider"] == "openai"  # the failed switch changed nothing


def test_a_policy_can_allow_only_some_providers(registry):
    registry.secrets.set("openai", KEY)
    registry.secrets.set("anthropic", KEY.replace("sk-", "sk-ant-"))
    registry._policies = lambda: {"allow_online_models": True, "allowed_online_providers": ["anthropic"]}
    with pytest.raises(ModelError, match="turned off"):
        registry.select("openai", "gpt-4o-mini", consent=True)
    assert registry.select("anthropic", "claude-haiku-5-5", consent=True)["provider"] == "anthropic"
    enabled = {p["id"]: p["enabled"] for p in registry.public()["providers"]}
    assert enabled == {"ollama": True, "anthropic": True, "openai": False, "gemini": False, "custom": False}
    registry._policies = lambda: {"allow_online_models": True, "allowed_online_providers": []}
    assert registry.active()["local"] is True and registry.public()["policy"]["allow_online"] is False


def test_the_provider_lists_the_models_a_key_may_use(registry):
    assert registry.remote_models("openai")["message"] == "Save an API key for OpenAI first."
    registry.secrets.set("openai", KEY)
    assert registry.remote_models("openai") == {"ok": True, "models": ["gpt-4o-mini", "gpt-4o"]}
    registry.secrets.set("anthropic", KEY.replace("sk-", "sk-ant-"))
    assert registry.remote_models("anthropic")["models"][0] == "claude-opus-5-5"  # fixed list, no request needed
    registry.secrets.set("custom", KEY)
    assert "service's address" in registry.remote_models("custom")["message"]

    def broken(provider, key, base_url):
        raise ModelError("OpenAI rejected the API key. Check it in Model settings.")

    registry._remote_models = broken
    assert registry.remote_models("openai")["ok"] is False


def test_the_connection_test_works_for_each_provider(registry):
    assert registry.test("gemini", "gemini-2.0-flash")["message"] == "Save an API key for Gemini first."
    registry.secrets.set("gemini", GEMINI_KEY)
    assert registry.test("gemini", "gemini-2.0-flash")["ok"] is True
    assert registry.test("custom", "m")["message"] == "Save an API key for Custom first."
    registry.secrets.set("custom", KEY)
    assert registry.test("custom", "m")["message"].startswith("Enter the service's address")
    assert registry.test("custom", "m", base_url=CUSTOM_URL)["ok"] is True
    registry.secrets.set("openai", KEY)
    assert registry.test("openai", "bad name!")["message"] == "Enter a valid model name."


# ---------- the HTTP API ----------
def test_keys_for_every_provider_are_saved_and_never_echoed(client):
    for provider, key in (("openai", KEY), ("gemini", GEMINI_KEY), ("custom", KEY.replace("sk-", "sk-cu-"))):
        saved = client.put("/api/models/key", json={"provider": provider, "key": key})
        assert saved.status_code == 200 and key not in saved.text
    public = client.get("/api/models")
    assert KEY not in public.text and GEMINI_KEY not in public.text
    assert [p["id"] for p in public.json()["providers"]] == ["ollama", "anthropic", "openai", "gemini", "custom"]
    assert client.put("/api/models/key", json={"provider": "ollama", "key": KEY}).status_code == 422


def test_choosing_openai_and_a_custom_service_through_the_api(client):
    client.put("/api/models/key", json={"provider": "openai", "key": KEY})
    chosen = client.post("/api/models/select", json={"provider": "openai", "model": "gpt-4o-mini", "consent": True})
    assert chosen.json()["active"]["label"] == "OpenAI · gpt-4o-mini"

    client.put("/api/models/key", json={"provider": "custom", "key": KEY})
    bad = client.post("/api/models/select", json={"provider": "custom", "model": "m", "consent": True, "base_url": "http://x.example.com"})
    assert bad.status_code == 400 and "https://" in bad.json()["detail"]
    ok = client.post("/api/models/select", json={"provider": "custom", "model": "m", "consent": True, "base_url": CUSTOM_URL})
    assert ok.json()["active"]["provider"] == "custom"

    available = client.post("/api/models/available", json={"provider": "openai"}).json()
    assert available == {"ok": True, "models": ["gpt-4o-mini", "gpt-4o"]}
    assert client.post("/api/models/test", json={"provider": "custom", "model": "m", "base_url": CUSTOM_URL}).json()["ok"] is True

    assert client.delete("/api/models/key/custom").json()["active"]["local"] is True


def test_listing_models_and_testing_are_refused_from_other_computers(client):
    from fastapi.testclient import TestClient

    from src import api as api_module

    remote = TestClient(api_module.api, client=("203.0.113.9", 50000))
    assert remote.post("/api/models/available", json={"provider": "openai"}).status_code == 403
    assert remote.post("/api/models/test", json={"provider": "custom", "model": "m", "base_url": CUSTOM_URL}).status_code == 403
