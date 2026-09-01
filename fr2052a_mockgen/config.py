"""Environment configuration for optional LLM features.

Loads OpenRouter settings from a .env file (if present) or the process
environment. Only tools/generate_profiles.py needs these; the core data
generator does not.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (no external dependency).

    Populates os.environ with KEY=VALUE lines that are not already set. Lines
    starting with '#' and blank lines are ignored. Existing environment
    variables take precedence and are never overwritten.
    """
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    base_url: str
    model: str


class ConfigError(RuntimeError):
    """Raised when required OpenRouter settings are missing."""


def load_openrouter_config(dotenv_path: str | Path = ".env") -> OpenRouterConfig:
    """Load OpenRouter settings, reading .env first.

    Raises ConfigError if the API key is not available.
    """
    load_dotenv(dotenv_path)
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet").strip()
    if not api_key:
        raise ConfigError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add "
            "your key (the .env file is gitignored)."
        )
    return OpenRouterConfig(api_key=api_key, base_url=base_url, model=model)
