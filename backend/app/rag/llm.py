"""Optional connection to a language model. Everything works without it."""
from typing import Protocol

import httpx

from app.config import Settings


class LLMError(Exception):
    """Something went wrong talking to the provider. The message never contains secrets."""


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


def _post(client: httpx.Client, url: str, headers: dict[str, str], payload: dict) -> dict:
    try:
        response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise LLMError("the provider timed out") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach the provider ({type(exc).__name__})") from None
    if response.status_code >= 400:
        raise LLMError(f"the provider returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise LLMError("the provider returned something that is not JSON") from None


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str | None, timeout: float, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._key = api_key
        self._url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, system: str, user: str) -> str:
        data = _post(
            self._http,
            self._url,
            {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {"model": self.model, "max_tokens": 700, "system": system, "messages": [{"role": "user", "content": user}]},
        )
        try:
            return "".join(b["text"] for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError):
            raise LLMError("unexpected response shape from the provider") from None


class OpenAICompatibleClient:
    """Works with OpenAI and with local servers such as Ollama or LM Studio (which need no key)."""

    provider = "openai_compatible"

    def __init__(self, api_key: str | None, model: str, base_url: str | None, timeout: float, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._key = api_key
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, system: str, user: str) -> str:
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        data = _post(
            self._http,
            self._url,
            headers,
            {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape from the provider") from None


def describe_provider(settings: Settings) -> tuple[bool, str | None]:
    """(is it usable, what is wrong if not)"""
    provider = settings.llm_provider
    if provider == "none":
        return False, None
    if provider not in ("anthropic", "openai_compatible"):
        return False, f"unknown provider '{provider}' (use none, anthropic or openai_compatible)"
    if not settings.llm_model:
        return False, "GRAPHGUARD_LLM_MODEL is not set"
    if provider == "anthropic" and not settings.llm_api_key:
        return False, "GRAPHGUARD_LLM_API_KEY is not set"
    return True, None


def build_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> LLMClient | None:
    usable, _ = describe_provider(settings)
    if not usable:
        return None
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    assert settings.llm_model
    if settings.llm_provider == "anthropic":
        return AnthropicClient(key or "", settings.llm_model, settings.llm_base_url, settings.llm_timeout_seconds, transport)
    return OpenAICompatibleClient(key, settings.llm_model, settings.llm_base_url, settings.llm_timeout_seconds, transport)