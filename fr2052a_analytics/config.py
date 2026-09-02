"""Load and access analytics configuration (factors and rules).

Configuration is JSON and lives in a config directory (default
``analytics_config``). Keeping factors and rules in editable config files lets
analysts tune runoff rates, HQLA treatment, and rule thresholds without code
changes, mirroring the schema-driven philosophy of the phase-1 generator.
"""
from __future__ import annotations

import json
from pathlib import Path

from .cli import ConfigError

FACTORS_FILE = "factors.json"
RULES_FILE = "rules.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object.")
    return data


def load_factors(config_dir: Path) -> dict:
    """Load the metric factors config from ``config_dir/factors.json``."""
    return _read_json(Path(config_dir) / FACTORS_FILE)


def load_rules(config_dir: Path) -> list[dict]:
    """Load rule definitions from ``config_dir/rules.json``.

    The file is an object with a top-level ``rules`` array.
    """
    data = _read_json(Path(config_dir) / RULES_FILE)
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise ConfigError(f"{RULES_FILE} must contain a 'rules' array.")
    return rules


def load_severity_definitions(config_dir: Path) -> dict:
    """Load the plain-language severity definitions from ``config_dir/rules.json``.

    Returns the top-level ``severity_definitions`` object, or an empty dict if
    the key is absent.
    """
    data = _read_json(Path(config_dir) / RULES_FILE)
    return data.get("severity_definitions", {})
