"""Streamlit-free admin operations for the FR 2052a tooling.

This module backs the local Admin console (``pages/1_Admin.py``). It contains
NO Streamlit imports so every operation is unit-testable without a running UI.

Capabilities:
    * List / read / validate / save bank profiles.
    * Read / validate / save analytics config (``factors.json``, ``rules.json``).
    * Generate mock data into an output directory (reusing the phase-1 generator).

Safety guarantees for every write:
    * **Validate before save** — invalid profiles/config raise before any file
      is touched.
    * **Timestamped backup** — the previous file is copied to
      ``<name>.<YYYYMMDD_HHMMSS>.bak`` beside the original before overwriting.
    * **Atomic write** — content is written to a temp file in the same directory
      then ``os.replace``d onto the target, so a crash never leaves a partial
      file.

This is a LOCAL admin helper with no authentication; it is intended for the
single-user demo/analysis workflow, not a multi-tenant deployment.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from fr2052a_mockgen import cli as mockgen_cli
from fr2052a_mockgen.profiles import ProfileError, validate_profile

from .cli import ConfigError
from .config import FACTORS_FILE, RULES_FILE

VALID_FORMATS = ("csv", "json")
SEVERITIES = ("info", "low", "medium", "high", "critical")


# --------------------------------------------------------------------------
# Low-level file helpers
# --------------------------------------------------------------------------

def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in same dir + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    finally:
        # If replace succeeded the temp file is gone; clean up on failure.
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def backup_file(path: Path) -> Path | None:
    """Copy ``path`` to a timestamped ``.bak`` beside it. Return the backup path.

    Returns ``None`` if the file does not exist (nothing to back up).
    """
    path = Path(path)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def _write_json_with_backup(path: Path, data: dict) -> Path:
    """Back up then atomically write ``data`` as pretty JSON. Return the path."""
    path = Path(path)
    backup_file(path)
    atomic_write(path, json.dumps(data, indent=2))
    return path


# --------------------------------------------------------------------------
# Bank profiles
# --------------------------------------------------------------------------

def list_profiles(profiles_dir) -> list[str]:
    """Return sorted bank names that have a ``<Bank>.json`` profile file."""
    p = Path(profiles_dir)
    if not p.exists() or not p.is_dir():
        return []
    names = [f.stem for f in p.glob("*.json") if f.is_file()]
    return sorted(names)


def read_profile_raw(profiles_dir, bank: str) -> dict:
    """Read ``<Bank>.json`` as a dict. Raise ProfileError if missing/invalid."""
    path = Path(profiles_dir) / f"{bank}.json"
    if not path.is_file():
        raise ProfileError(f"Profile file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Profile is not valid JSON ({path}): {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"Profile root must be a JSON object ({path})")
    return raw


def _profile_to_dict(profile) -> dict:
    """Serialize a validated BankProfile to the profile JSON shape."""
    d = dataclasses.asdict(profile)
    # Preserve a stable, human-friendly key order.
    return {
        "bank": d.get("bank", ""),
        "description": d.get("description", ""),
        "table_weights": d.get("table_weights", {}),
        "product_weights": d.get("product_weights", {}),
        "amount_scale": d.get("amount_scale", {}),
        "counterparty_distribution": d.get("counterparty_distribution", {}),
        "collateral_distribution": d.get("collateral_distribution", {}),
    }


def validate_profile_raw(raw: dict, schema) -> tuple[dict, list[str]]:
    """Validate a raw profile dict against ``schema``.

    Returns ``(cleaned_dict, warnings)``. Unknown products / prefixes /
    counterparties / collateral classes are dropped and reported as warnings.
    Raises ProfileError on a fatal problem (e.g. missing ``bank``).
    """
    result = validate_profile(raw, schema)
    return _profile_to_dict(result.profile), list(result.warnings)


def save_profile(profiles_dir, bank: str, raw: dict, schema) -> tuple[Path, list[str]]:
    """Validate then save the profile for ``bank``. Return (path, warnings)."""
    cleaned, warnings = validate_profile_raw(raw, schema)
    # Force the bank name to match the target file to avoid drift.
    cleaned["bank"] = bank
    path = Path(profiles_dir) / f"{bank}.json"
    _write_json_with_backup(path, cleaned)
    return path, warnings


# --------------------------------------------------------------------------
# Analytics config: factors.json and rules.json
# --------------------------------------------------------------------------

def read_factors(config_dir) -> dict:
    """Read ``factors.json`` as a dict. Raise ConfigError on missing/invalid."""
    return _read_config_json(Path(config_dir) / FACTORS_FILE)


def read_rules_doc(config_dir) -> dict:
    """Read the RAW ``rules.json`` document (whole object, not just the list)."""
    return _read_config_json(Path(config_dir) / RULES_FILE)


def _read_config_json(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object.")
    return data


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_factors(raw: dict) -> dict:
    """Lightweight sanity-check of a factors dict. Return it unchanged if OK.

    Catches obviously broken edits without over-constraining the schema.
    """
    if not isinstance(raw, dict):
        raise ConfigError("factors config must be a JSON object.")

    hqla = raw.get("hqla")
    if isinstance(hqla, dict):
        haircuts = hqla.get("haircut_by_level")
        if isinstance(haircuts, dict):
            for level, v in haircuts.items():
                if not _is_number(v) or not (0.0 <= float(v) <= 1.0):
                    raise ConfigError(
                        f"hqla.haircut_by_level['{level}'] must be a number in [0, 1], got {v!r}."
                    )

    analytics = raw.get("analytics")
    if isinstance(analytics, dict):
        anomaly = analytics.get("anomaly")
        if isinstance(anomaly, dict):
            for key in ("zscore_threshold", "iqr_multiplier", "day_over_day_pct_jump"):
                if key in anomaly and not _is_number(anomaly[key]):
                    raise ConfigError(f"analytics.anomaly.{key} must be a number, got {anomaly[key]!r}.")

    inflow = raw.get("inflow_rate")
    if isinstance(inflow, dict) and "inflow_cap_pct_of_outflows" in inflow:
        cap = inflow["inflow_cap_pct_of_outflows"]
        if not _is_number(cap) or not (0.0 <= float(cap) <= 1.0):
            raise ConfigError(
                f"inflow_rate.inflow_cap_pct_of_outflows must be a number in [0, 1], got {cap!r}."
            )

    return raw


def validate_rules_doc(doc: dict) -> dict:
    """Validate a rules.json document. Return it unchanged if OK.

    Reuses the rule engine's per-rule validation so the UI and engine agree.
    """
    if not isinstance(doc, dict):
        raise ConfigError("rules config must be a JSON object.")
    rules = doc.get("rules")
    if not isinstance(rules, list):
        raise ConfigError("rules.json must contain a 'rules' array.")

    # Import here to avoid a circular import at module load.
    from .rules import _validate_rule

    for rule in rules:
        if not isinstance(rule, dict):
            raise ConfigError(f"Each rule must be a JSON object, got {type(rule).__name__}.")
        _validate_rule(rule)

    sev_defs = doc.get("severity_definitions")
    if sev_defs is not None and not isinstance(sev_defs, dict):
        raise ConfigError("severity_definitions must be a JSON object.")

    return doc


def save_factors(config_dir, raw: dict) -> Path:
    """Validate then save ``factors.json``. Return the path."""
    validate_factors(raw)
    return _write_json_with_backup(Path(config_dir) / FACTORS_FILE, raw)


def save_rules_doc(config_dir, doc: dict) -> Path:
    """Validate then save ``rules.json``. Return the path."""
    validate_rules_doc(doc)
    return _write_json_with_backup(Path(config_dir) / RULES_FILE, doc)


# --------------------------------------------------------------------------
# Mock data generation (reuses the phase-1 generator)
# --------------------------------------------------------------------------

def _clear_output_files(out_dir: Path) -> int:
    """Delete only FR2052a_*.csv / FR2052a_*.json files in ``out_dir``.

    Returns the number of files removed. A missing directory is a no-op.
    """
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return 0
    removed = 0
    for pattern in ("FR2052a_*.csv", "FR2052a_*.json"):
        for f in out_dir.glob(pattern):
            if f.is_file():
                f.unlink()
                removed += 1
    return removed


def generate_data(banks: list[str], start: date, days: int, fmt: str,
                  out_dir, profiles_dir, schema_path,
                  seed: int | None = None, clear_output: bool = False) -> list[Path]:
    """Generate mock FR 2052a data into ``out_dir`` (append by default).

    Reuses the phase-1 generator (``fr2052a_mockgen.cli.run``). Returns the list
    of written file paths. ProfileError / SchemaError propagate to the caller.

    Args:
        banks: bank names (each must have a profile in ``profiles_dir``).
        start: first reporting date.
        days: number of consecutive days (>= 1).
        fmt: 'csv' or 'json'.
        out_dir: output directory (created if missing).
        profiles_dir: directory of bank profile JSON files.
        schema_path: schema file path.
        seed: optional RNG seed for reproducibility.
        clear_output: if True, delete existing FR2052a_* files first.
    """
    if not banks:
        raise ValueError("Select at least one bank to generate.")
    if days < 1:
        raise ValueError("Days must be >= 1.")
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}' (expected one of {VALID_FORMATS}).")

    if clear_output:
        _clear_output_files(Path(out_dir))

    config = mockgen_cli.Config(
        banks=list(banks),
        start=start,
        days=int(days),
        fmt=fmt,
        out=Path(out_dir),
        schema=Path(schema_path),
        seed=seed,
        profiles=Path(profiles_dir),
    )
    return mockgen_cli.run(config)
