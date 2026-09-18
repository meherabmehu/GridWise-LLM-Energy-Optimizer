"""Runtime configuration for the GridWise service.

All configuration is read from environment variables so the same image can run
locally, in Docker, and on a hosting platform without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# provider -> (default base url, default model, provider specific key variable)
PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "GROQ_API_KEY"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.0-flash",
        "GEMINI_API_KEY",
    ),
    "openai_compatible": ("", "", "LLM_API_KEY"),
}

DEFAULT_PROVIDER = "groq"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env(name, str(default))))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "")
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable view of the process configuration."""

    provider: str
    api_key: str
    base_url: str
    model: str
    enabled: bool
    timeout_seconds: float
    max_attempts: int
    max_tokens: int
    temperature: float
    cache_size: int
    cache_ttl_seconds: float
    host: str
    port: int
    log_level: str

    @property
    def llm_available(self) -> bool:
        """True when a language model is configured and reachable in principle."""
        return bool(self.enabled and self.api_key and self.base_url and self.model)

    @property
    def model_label(self) -> str:
        return f"{self.provider}:{self.model}" if self.model else self.provider


def load_settings() -> Settings:
    """Build a :class:`Settings` instance from the current environment."""
    provider = _env("LLM_PROVIDER", DEFAULT_PROVIDER).lower() or DEFAULT_PROVIDER
    base_default, model_default, key_variable = PROVIDER_DEFAULTS.get(
        provider, ("", "", "LLM_API_KEY")
    )

    api_key = _env("LLM_API_KEY") or _env(key_variable)
    base_url = _env("LLM_BASE_URL", base_default).rstrip("/")
    model = _env("LLM_MODEL", model_default)

    return Settings(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        enabled=_env_bool("LLM_ENABLED", True),
        timeout_seconds=max(_env_float("LLM_TIMEOUT_SECONDS", 12.0), 0.5),
        max_attempts=max(_env_int("LLM_MAX_ATTEMPTS", 2), 1),
        max_tokens=max(_env_int("LLM_MAX_TOKENS", 1200), 128),
        temperature=_env_float("LLM_TEMPERATURE", 0.0),
        cache_size=max(_env_int("LLM_CACHE_SIZE", 512), 0),
        cache_ttl_seconds=max(_env_float("LLM_CACHE_TTL_SECONDS", 900.0), 0.0),
        host=_env("HOST", "0.0.0.0") or "0.0.0.0",
        port=_env_int("PORT", 8000),
        log_level=_env("LOG_LEVEL", "info").lower() or "info",
    )
