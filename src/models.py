"""Which model writes the answers, where it runs, and the API key behind it.

Two kinds of model:
  - local: a model served by Ollama on this computer. Nothing leaves the machine.
  - online: Claude (Anthropic's official SDK), OpenAI, Google Gemini, or any OpenAI-compatible service. Each
    question and the document passages found for it are sent to that provider, so it is opt-in, needs an
    explicit confirmation, and can be switched off entirely (or restricted to some providers) in
    data/policies.json.

Search always uses the local embedding model, whichever model writes the answer.

API keys are never stored in a file or sent back to the browser. They live in the operating system's
credential store (Windows Credential Manager), or come from an environment variable, which always wins.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

import config
from src.policy import load_policies

SERVICE = "field-assist"

# Prices are list prices per million tokens, shown to help choose; Anthropic's pricing page is the authority.
ANTHROPIC_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "price": "$4 in / $20 out per million tokens"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "price": "$2 in / $10 out per million tokens"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "price": "$0.10 in / $0.50 out per million tokens"},
]
# Server-side refusal fallback ("default") is offered for these two on the Claude API; Haiku 5.5 has none.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class ModelError(RuntimeError):
    """A failure whose message is safe and useful to show to the engineer."""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str  # shown in the settings panel
    short: str  # used in the header and on answers
    kind: str  # "anthropic" (official SDK) or "openai" (the OpenAI-compatible protocol)
    env_var: str
    sends_to: str | None  # who receives the questions; None for a custom address (shown as its host)
    base_url: str | None = None  # fixed for presets, None when the user supplies it
    key_hint: str = "API key"
    models: tuple = ()  # suggested models; empty means "ask the provider"

    @property
    def needs_base_url(self) -> bool:
        """Only the custom provider takes an address from the user; Anthropic's SDK knows its own."""
        return self.kind == "openai" and self.base_url is None


ONLINE_PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("anthropic", "Anthropic (Claude)", "Claude", "anthropic", "ANTHROPIC_API_KEY", "Anthropic",
                 key_hint="sk-ant-…", models=tuple(ANTHROPIC_MODELS)),
        Provider("openai", "OpenAI", "OpenAI", "openai", "OPENAI_API_KEY", "OpenAI",
                 base_url="https://api.openai.com/v1", key_hint="sk-…"),
        # Google publishes an OpenAI-compatible endpoint for Gemini, so the same adapter serves it.
        Provider("gemini", "Google Gemini", "Gemini", "openai", "GEMINI_API_KEY", "Google",
                 base_url="https://generativelanguage.googleapis.com/v1beta/openai/", key_hint="AIza…"),
        Provider("custom", "Other (OpenAI-compatible)", "Custom", "openai", "FIELD_ASSIST_CUSTOM_API_KEY", None),
    )
}
_MODEL_ID = re.compile(r"^[A-Za-z0-9._:/\-]{1,100}$")
_NOT_CHAT = ("embed", "whisper", "tts", "dall", "moderation", "transcribe", "imagen", "veo", "aqa", "image")


def validate_base_url(url: str | None) -> str:
    """A custom endpoint must be https (http only for this computer) and carry no credentials."""
    url = (url or "").strip()
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if len(url) > 300 or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ModelError("Enter the service's address, for example https://api.example.com/v1")
    if parsed.scheme == "http" and not local:
        raise ModelError("Use an https:// address. Plain http:// is only allowed for this computer.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelError("The address must not contain a password, query or fragment.")
    return url.rstrip("/")


# ---------------------------------------------------------------- secrets
class SecretStore:
    """API keys in the OS credential store, with an environment variable taking precedence."""

    def __init__(self, backend=None, environ=None):
        self._backend = backend
        self._environ = environ if environ is not None else os.environ

    @property
    def backend(self):
        if self._backend is None:
            import keyring

            self._backend = keyring
        return self._backend

    @staticmethod
    def env_var(provider: str) -> str | None:
        known = ONLINE_PROVIDERS.get(provider)
        return known.env_var if known else None

    def can_store(self) -> bool:
        """False on a machine with no secure credential store (for example a bare Linux server)."""
        try:
            from keyring.backends import fail

            return not isinstance(self.backend.get_keyring(), fail.Keyring)
        except AttributeError:
            return True  # an injected backend without get_keyring() is assumed to work
        except Exception:
            return False

    def get(self, provider: str) -> tuple[str | None, str | None]:
        """(key, source) where source is 'env', 'store' or None. The key is for server-side use only."""
        env = (self._environ.get(self.env_var(provider) or "") or "").strip()
        if env:
            return env, "env"
        try:
            stored = self.backend.get_password(SERVICE, provider)
        except Exception:
            stored = None
        return (stored, "store") if stored else (None, None)

    def set(self, provider: str, key: str) -> None:
        key = (key or "").strip()
        if len(key) < 20 or any(ch.isspace() for ch in key):
            raise ModelError("That doesn't look like an API key. Paste the whole key with no spaces.")
        if not self.can_store():
            raise ModelError(
                "This computer has no secure place to keep the key. "
                f"Set the {self.env_var(provider) or 'API key'} environment variable instead and restart the app."
            )
        try:
            self.backend.set_password(SERVICE, provider, key)
        except Exception:
            raise ModelError("Couldn't save the key to the operating system's credential store.") from None

    def delete(self, provider: str) -> None:
        try:
            self.backend.delete_password(SERVICE, provider)
        except Exception:
            pass  # nothing stored is the same as deleted

    def status(self, provider: str) -> dict:
        key, source = self.get(provider)
        return {
            "saved": bool(key),
            "source": source,
            "hint": f"…{key[-4:]}" if key else None,  # only the last four characters ever leave the server
            "can_store": self.can_store(),
            "env_var": self.env_var(provider),
        }


# ---------------------------------------------------------------- clients
class AnthropicChat:
    """Claude through the official SDK, exposed as the `invoke(prompt) -> str` the agent expects."""

    provider = "anthropic"

    def __init__(self, model: str, api_key: str, client=None):
        self.model = model
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
        self._client = client

    def invoke(self, prompt: str) -> str:
        import anthropic

        request = dict(
            model=self.model,
            max_tokens=4096,
            output_config={"effort": "low"},  # grounded, extractive answers don't need deep reasoning
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            if self.model in FALLBACK_MODELS:
                response = self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **request)
            else:
                response = self._client.messages.create(**request)
        except anthropic.AuthenticationError:
            raise ModelError("Anthropic rejected the API key. Check it in Model settings.") from None
        except anthropic.PermissionDeniedError:
            raise ModelError("This API key isn't allowed to use that model.") from None
        except anthropic.NotFoundError:
            raise ModelError(f"Anthropic doesn't recognise the model '{self.model}'.") from None
        except anthropic.RateLimitError:
            raise ModelError("Anthropic's rate limit was reached. Wait a moment and try again.") from None
        except anthropic.BadRequestError as exc:
            raise ModelError(f"Anthropic rejected the request: {str(exc.message)[:200]}") from None
        except anthropic.APITimeoutError:
            raise ModelError("Anthropic took too long to answer. Try again, or switch to the local model.") from None
        except anthropic.APIConnectionError:
            raise ModelError("Can't reach Anthropic. Check the internet connection, or switch to the local model.") from None
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelError("Anthropic is busy or having problems. Try again shortly.") from None
            raise ModelError(f"Anthropic returned an error ({exc.status_code}).") from None

        if response.stop_reason == "refusal":
            raise ModelError("Anthropic's safety systems declined this request. Rephrase it, or use the local model.")
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise ModelError("The model ran out of room before it answered. Try again.")
        return text


def _openai_error(exc: Exception, who: str, model: str) -> ModelError:
    """Turn an OpenAI-SDK failure into a plain message. Never includes the request, so never the key."""
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return ModelError(f"{who} rejected the API key. Check it in Model settings.")
    if isinstance(exc, openai.PermissionDeniedError):
        return ModelError("This API key isn't allowed to use that model.")
    if isinstance(exc, openai.NotFoundError):
        return ModelError(f"{who} doesn't recognise the model '{model}'. Pick one from the list.")
    if isinstance(exc, openai.RateLimitError):
        return ModelError(f"{who}'s rate limit or quota was reached. Wait a moment, or check the account's billing.")
    if isinstance(exc, openai.BadRequestError):
        return ModelError(f"{who} rejected the request: {str(getattr(exc, 'message', ''))[:200]}")
    if isinstance(exc, openai.APITimeoutError):
        return ModelError(f"{who} took too long to answer. Try again, or switch to the local model.")
    if isinstance(exc, openai.APIConnectionError):
        return ModelError(f"Can't reach {who}. Check the internet connection and the address, or switch to the local model.")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return ModelError(f"{who} is busy or having problems. Try again shortly.")
        return ModelError(f"{who} returned an error ({exc.status_code}).")
    return ModelError(f"{who} returned an unexpected error.")


class OpenAICompatibleChat:
    """Any service that speaks the OpenAI chat protocol: OpenAI itself, Gemini's compatible endpoint, or a custom
    address. Deliberately sends only the model and the prompt: no temperature, token limit or reasoning options,
    because each of those is rejected by some models or services."""

    def __init__(self, who: str, model: str, api_key: str, base_url: str, client=None):
        self.who = who
        self.model = model.removeprefix("models/")  # Gemini lists models as "models/<name>"
        if client is None:
            import openai

            client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=2)
        self._client = client

    def invoke(self, prompt: str) -> str:
        import openai

        try:
            response = self._client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}]
            )
        except openai.OpenAIError as exc:
            raise _openai_error(exc, self.who, self.model) from None
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise ModelError(f"{self.who} returned no answer.")
        if choice.finish_reason == "content_filter":
            raise ModelError(f"{self.who}'s safety filter blocked this request. Rephrase it, or use the local model.")
        text = (choice.message.content or "").strip()
        if not text:
            raise ModelError(
                f"{self.who} ran out of room before it answered." if choice.finish_reason == "length"
                else f"{self.who} returned an empty answer."
            )
        return text


def installed_ollama_chat_models() -> list[str]:
    """Chat models installed in Ollama (embedding models are left out). Empty if Ollama isn't running."""
    try:
        response = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        names = [m["name"] for m in response.json().get("models", [])]
    except Exception:
        return []
    return sorted(n for n in names if "embed" not in n.lower())


def _local_llm(model: str):
    from src.graph import make_llm

    return make_llm(model)


def _default_online_factory(provider_id: str, model: str, key: str, base_url: str | None):
    provider = ONLINE_PROVIDERS[provider_id]
    if provider.kind == "anthropic":
        return AnthropicChat(model, key)
    return OpenAICompatibleChat(provider.short, model, key, base_url or provider.base_url or "")


def _default_remote_models(provider_id: str, key: str, base_url: str | None) -> list[str]:
    """Ask the provider which models this key can use, so the list never goes stale."""
    import openai

    provider = ONLINE_PROVIDERS[provider_id]
    client = openai.OpenAI(api_key=key, base_url=base_url or provider.base_url, timeout=20.0, max_retries=1)
    try:
        ids = {m.id.removeprefix("models/") for m in client.models.list()}
    except openai.OpenAIError as exc:
        raise _openai_error(exc, provider.short, "") from None
    return sorted(i for i in ids if not any(word in i.lower() for word in _NOT_CHAT))[:200]


# ---------------------------------------------------------------- registry
class ModelRegistry:
    """The active model, chosen at runtime. The agent talks to it through SwitchableLLM, so a switch
    takes effect on the next question without restarting anything."""

    def __init__(
        self,
        secrets: SecretStore | None = None,
        settings_path: str | Path | None = None,
        local_factory: Callable[[str], object] = _local_llm,
        online_factory: Callable[[str, str, str, str | None], object] = _default_online_factory,
        ollama_models_fn: Callable[[], list[str]] = installed_ollama_chat_models,
        policies_fn: Callable[[], dict] = load_policies,
        remote_models_fn: Callable[[str, str, str | None], list[str]] = _default_remote_models,
    ):
        self.secrets = secrets or SecretStore()
        self._path = Path(settings_path or config.MODEL_SETTINGS_JSON)
        self._local_factory = local_factory
        self._online_factory = online_factory
        self._ollama_models = ollama_models_fn
        self._policies = policies_fn
        self._remote_models = remote_models_fn
        self._lock = threading.Lock()
        self._clients: dict[tuple, object] = {}

    # ----- settings file (no secrets in it)
    def _settings(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, settings: dict, keep_custom_url: bool = True) -> None:
        if keep_custom_url:
            existing = self._settings().get("custom_base_url")
            if existing and "custom_base_url" not in settings:
                settings = {**settings, "custom_base_url": existing}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def provider_allowed(self, provider_id: str) -> bool:
        policy = self._policies()
        if not policy.get("allow_online_models", True):
            return False
        allowed = policy.get("allowed_online_providers")
        return allowed is None or provider_id in allowed

    def online_allowed(self) -> bool:
        return any(self.provider_allowed(p) for p in ONLINE_PROVIDERS)

    def _base_url(self, provider_id: str, requested: str | None = None) -> str | None:
        """The address to call: fixed for presets, validated user input for the custom provider, none for Claude."""
        provider = ONLINE_PROVIDERS[provider_id]
        if provider.needs_base_url:
            return validate_base_url(requested or self._settings().get("custom_base_url"))
        return provider.base_url

    @staticmethod
    def _model_ok(provider: Provider, model: str | None) -> bool:
        if provider.models:
            return model in {m["id"] for m in provider.models}
        return bool(model) and bool(_MODEL_ID.match(model))

    # ----- what is active
    def _online_blocker(self, provider_id: str, model: str | None, settings: dict) -> str | None:
        provider = ONLINE_PROVIDERS.get(provider_id)
        if provider is None:
            return "The saved provider isn't available."
        if not self.provider_allowed(provider_id):
            return "This provider is turned off by data/policies.json."
        if not self._model_ok(provider, model):
            return "The saved online model isn't valid."
        if not self.secrets.get(provider_id)[0]:
            return f"No API key is saved for {provider.short}."
        if provider.needs_base_url:
            try:
                validate_base_url(settings.get("custom_base_url"))
            except ModelError:
                return "The saved service address isn't valid."
        if not settings.get("consent"):
            return "Online use hasn't been confirmed."
        return None

    def _where(self, provider: Provider, settings: dict) -> str:
        if provider.sends_to:
            return f"{provider.sends_to}'s servers (online)"
        host = urlparse(settings.get("custom_base_url") or "").hostname or "a custom address"
        return f"{host} (online)"

    def active(self) -> dict:
        """The model that will write the next answer. Falls back to the local model, and says why, whenever the
        online one can't be used (key removed, company policy, no confirmation)."""
        settings = self._settings()
        provider_id, model, note = settings.get("provider", "ollama"), settings.get("model"), None
        if provider_id != "ollama":
            note = self._online_blocker(provider_id, model, settings)
            if note:
                provider_id, model = "ollama", None
        if provider_id != "ollama":
            provider = ONLINE_PROVIDERS[provider_id]
            label = (
                next(m["label"] for m in provider.models if m["id"] == model)
                if provider.models
                else f"{provider.short} · {model}"
            )
            return {"provider": provider_id, "model": model, "label": label, "local": False,
                    "where": self._where(provider, settings), "note": None}
        model = model or config.CHAT_MODEL
        return {"provider": "ollama", "model": model, "label": model, "local": True,
                "where": "This computer (Ollama)", "note": note}

    def active_id(self) -> str:
        active = self.active()
        return f"{active['provider']}:{active['model']}"

    def llm(self):
        """The client for the active model, built once and reused."""
        active = self.active()
        if active["local"]:
            token = ("ollama", active["model"], "", "")
            build = lambda: self._local_factory(active["model"])  # noqa: E731
        else:
            key = self.secrets.get(active["provider"])[0] or ""
            base_url = self._base_url(active["provider"])
            token = (active["provider"], active["model"], hashlib.sha256(key.encode()).hexdigest()[:12], base_url or "")
            build = lambda: self._online_factory(active["provider"], active["model"], key, base_url)  # noqa: E731
        with self._lock:
            if token not in self._clients:
                self._clients = {token: build()}  # only the active one is worth keeping
            return self._clients[token]

    # ----- changes
    def select(self, provider: str, model: str, consent: bool = False, base_url: str | None = None) -> dict:
        if provider == "ollama":
            installed = self._ollama_models()
            if not installed:
                raise ModelError("Can't read the installed models. Is Ollama running?")
            if model not in installed:
                raise ModelError(f"'{model}' isn't installed in Ollama. Run: ollama pull {model}")
            self._save({"provider": "ollama", "model": model, "consent": False})
            return self.active()

        known = ONLINE_PROVIDERS.get(provider)
        if known is None:
            raise ModelError("Unknown provider.")
        if not self.provider_allowed(provider):
            raise ModelError("This provider is turned off by data/policies.json.")
        if not self._model_ok(known, model):
            raise ModelError("Choose one of the listed Claude models." if known.models else "Enter a valid model name.")
        if not self.secrets.get(provider)[0]:
            raise ModelError(f"Save an API key for {known.short} first.")
        settings = {"provider": provider, "model": model, "consent": True,
                    "consented_at": datetime.now().isoformat(timespec="seconds")}
        if known.needs_base_url:
            settings["custom_base_url"] = self._base_url(provider, base_url)
        if not consent:
            raise ModelError(f"Confirm that you understand questions and document passages are sent to {self._who(known, settings)}.")
        self._save(settings)
        return self.active()

    def _who(self, provider: Provider, settings: dict) -> str:
        return provider.sends_to or urlparse(settings.get("custom_base_url") or "").hostname or "that service"

    def forget_online_choice(self, provider: str) -> None:
        """Called when a key is removed: the confirmation was for that key, so a later key starts from local."""
        if self._settings().get("provider") == provider:
            self._save({"provider": "ollama", "model": None, "consent": False})

    def remote_models(self, provider: str, base_url: str | None = None) -> dict:
        """The models this provider says the saved key can use (so the list is never out of date)."""
        known = ONLINE_PROVIDERS.get(provider)
        try:
            if known is None or not self.provider_allowed(provider):
                raise ModelError("This provider isn't available.")
            key = self.secrets.get(provider)[0]
            if not key:
                raise ModelError(f"Save an API key for {known.short} first.")
            if known.models:
                return {"ok": True, "models": [m["id"] for m in known.models]}
            return {"ok": True, "models": self._remote_models(provider, key, self._base_url(provider, base_url))}
        except ModelError as exc:
            return {"ok": False, "message": str(exc)}

    def test(self, provider: str, model: str, base_url: str | None = None) -> dict:
        """One tiny request to check the model answers (and, for online models, that the key works)."""
        try:
            if provider == "ollama":
                client = self._local_factory(model)
            else:
                known = ONLINE_PROVIDERS.get(provider)
                if known is None:
                    raise ModelError("Unknown provider.")
                if not self.provider_allowed(provider):
                    raise ModelError("This provider is turned off by data/policies.json.")
                key = self.secrets.get(provider)[0]
                if not key:
                    raise ModelError(f"Save an API key for {known.short} first.")
                if not self._model_ok(known, model):
                    raise ModelError("Choose one of the listed Claude models." if known.models else "Enter a valid model name.")
                client = self._online_factory(provider, model, key, self._base_url(provider, base_url))
            started = time.perf_counter()
            reply = client.invoke("Reply with the single word OK.")
            reply = getattr(reply, "content", reply)
            return {"ok": True, "ms": round((time.perf_counter() - started) * 1000), "reply": str(reply).strip()[:40]}
        except ModelError as exc:
            return {"ok": False, "message": str(exc)}
        except Exception as exc:  # a local model that isn't running, for instance
            text = str(exc)
            if "connect" in text.lower() or "refused" in text.lower():
                return {"ok": False, "message": "Can't reach Ollama. Start it, then try again."}
            return {"ok": False, "message": text[:200] or exc.__class__.__name__}

    # ----- what the UI shows (never a key)
    def public(self) -> dict:
        installed = self._ollama_models()
        active = self.active()
        if active["local"] and active["model"] not in installed:
            installed = sorted({active["model"], *installed})
        settings = self._settings()
        providers = [
            {
                "id": "ollama",
                "label": "On this computer",
                "local": True,
                "enabled": True,
                "note": "Runs through Ollama. Nothing leaves this machine, and it costs nothing per question.",
                "models": [{"id": m, "label": m, "price": "free"} for m in installed],
            }
        ]
        for provider in ONLINE_PROVIDERS.values():
            allowed = self.provider_allowed(provider.id)
            where = provider.sends_to or "the address you enter"
            providers.append(
                {
                    "id": provider.id,
                    "label": f"{provider.label}, online",
                    "local": False,
                    "enabled": allowed,
                    "note": (
                        f"Each question and the document passages found for it are sent to {where} to write the "
                        "answer, and billed to your API key. Searching and your documents stay on this machine."
                        if allowed
                        else "Turned off by data/policies.json."
                    ),
                    "key": {**self.secrets.status(provider.id), "placeholder": provider.key_hint},
                    "models": list(provider.models),
                    "sends_to": provider.sends_to,  # None for a custom address, which the UI names from what was typed
                    "needs_base_url": provider.needs_base_url,
                    "base_url": settings.get("custom_base_url") if provider.needs_base_url else provider.base_url,
                }
            )
        return {
            "active": active,
            "search": {"model": config.EMBED_MODEL, "where": "This computer (Ollama)", "local": True},
            "policy": {"allow_online": self.online_allowed()},
            "providers": providers,
        }


class SwitchableLLM:
    """What the agent holds: it forwards every call to whichever model is active right now."""

    def __init__(self, registry: ModelRegistry):
        self._registry = registry

    def invoke(self, prompt: str):
        return self._registry.llm().invoke(prompt)
