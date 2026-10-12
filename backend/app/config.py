from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels above backend/app/config.py -> graphguard/
REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """The settings are unsafe or inconsistent. Raised at startup so the app refuses to run."""


def _check_origin(origin: str) -> str | None:
    """Return a problem description, or None when the origin is a plain scheme://host[:port]."""
    if origin == "*":
        return "'*' (allow everyone) is not allowed"
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"'{origin}' is not a valid origin (use http://host:port)"
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return f"'{origin}' must not contain a path (use http://host:port)"
    return None


class Settings(BaseSettings):
    """All configuration lives here. Values come from environment variables
    prefixed GRAPHGUARD_ (or from a .env file), with safe defaults for development."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_prefix="GRAPHGUARD_",
        extra="ignore",
    )

    app_name: str = "GraphGuard API"
    version: str = "0.1.0"
    environment: Literal["development", "production", "test"] = "development"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    # API docs (/docs, /redoc, /openapi.json). Unset = on in development, off in production.
    docs_enabled: bool | None = None

    # Protection against oversized or abusive requests
    max_request_body_bytes: int = Field(1_000_000, ge=1_000)
    rate_limit_per_minute: int = Field(60, ge=1)

    # Origins (scheme + host + port) allowed to call this API from a browser.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Browser origins allowed to open a WebSocket (checked separately from CORS).
    ws_allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # SQLite file location. Default lives in <repo>/data/ (git-ignored).
    database_path: Path = REPO_ROOT / "data" / "graphguard.db"

    # Optional language model. Leave llm_provider as "none" to use rule-based summaries only.
    llm_provider: str = "none"  # none | anthropic | openai_compatible
    llm_api_key: SecretStr | None = None  # SecretStr never prints its value in logs or repr()
    llm_model: str | None = None
    llm_base_url: str | None = None  # e.g. http://localhost:11434/v1 for a local Ollama server
    llm_timeout_seconds: float = 30.0

    @field_validator("llm_model", "llm_base_url", "llm_api_key", "docs_enabled", mode="before")
    @classmethod
    def blank_means_unset(cls, value):
        """`GRAPHGUARD_LLM_MODEL=` (empty) must mean 'not set', not 'set to an empty string'."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def docs_are_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.environment != "production"

    def validate_for_environment(self) -> None:
        """Refuse to start with a configuration that is unsafe. Raises ConfigError listing every problem."""
        problems: list[str] = []
        for name in ("cors_origins", "ws_allowed_origins"):
            for origin in getattr(self, name):
                issue = _check_origin(origin)
                if issue:
                    problems.append(f"{name}: {issue}")
        if self.llm_provider not in ("none", "anthropic", "openai_compatible"):
            problems.append(f"llm_provider: unknown provider '{self.llm_provider}'")
        elif self.environment == "production" and self.llm_provider != "none":
            if not self.llm_model:
                problems.append("llm_model is required when an AI provider is enabled")
            if self.llm_provider == "anthropic" and not self.llm_api_key:
                problems.append("llm_api_key is required for the anthropic provider")
        if self.environment == "production" and not self.cors_origins:
            problems.append("cors_origins must list the frontend origin in production")
        if problems:
            raise ConfigError("Invalid configuration: " + "; ".join(problems))

    def summary(self) -> dict:
        """Safe-to-log description of the settings. Reports whether a key exists, never the key."""
        return {
            "environment": self.environment,
            "version": self.version,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "docs_enabled": self.docs_are_enabled,
            "database_path": str(self.database_path),
            "cors_origins": self.cors_origins,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_request_body_bytes": self.max_request_body_bytes,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_key_present": self.llm_api_key is not None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
