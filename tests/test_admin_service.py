"""Tests for the Streamlit-free admin_service module."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fr2052a_analytics import admin_service as adm
from fr2052a_analytics.cli import ConfigError
from fr2052a_mockgen.profiles import ProfileError, load_profile
from fr2052a_mockgen.schema_loader import load_schema

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "schema" / "fr2052a_schema.json"
CONFIG_DIR = REPO / "analytics_config"
PROFILES_DIR = REPO / "bank_profiles"


@pytest.fixture(scope="module")
def schema():
    return load_schema(SCHEMA_PATH)


# --- low-level helpers ------------------------------------------------------

def test_atomic_write_and_backup(tmp_path):
    p = tmp_path / "f.json"
    # No file yet -> backup returns None.
    assert adm.backup_file(p) is None
    adm.atomic_write(p, '{"a": 1}')
    assert json.loads(p.read_text()) == {"a": 1}
    # Now a backup is created.
    b = adm.backup_file(p)
    assert b is not None and b.exists()
    assert ".bak" in b.name


# --- profiles ---------------------------------------------------------------

def test_list_profiles(tmp_path):
    (tmp_path / "Wells.json").write_text("{}", encoding="utf-8")
    (tmp_path / "BoFA.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert adm.list_profiles(tmp_path) == ["BoFA", "Wells"]


def test_list_profiles_missing_dir(tmp_path):
    assert adm.list_profiles(tmp_path / "nope") == []


def test_read_profile_raw_missing(tmp_path):
    with pytest.raises(ProfileError):
        adm.read_profile_raw(tmp_path, "Ghost")


def test_read_profile_raw_invalid_json(tmp_path):
    (tmp_path / "Bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError):
        adm.read_profile_raw(tmp_path, "Bad")


def test_validate_profile_raw_drops_unknown(schema):
    raw = {
        "bank": "TestBank",
        "description": "d",
        "table_weights": {"O.D": 3.0, "NOPE": 5.0},
        "product_weights": {"O.D.1": 4.0, "X.Y.Z": 9.0},
        "collateral_distribution": {"I.A": {"A-1-Q": 2.0, "BOGUS": 1.0}},
    }
    cleaned, warnings = adm.validate_profile_raw(raw, schema)
    assert cleaned["table_weights"] == {"O.D": 3.0}
    assert cleaned["product_weights"] == {"O.D.1": 4.0}
    assert cleaned["collateral_distribution"]["I.A"] == {"A-1-Q": 2.0}
    assert warnings  # unknown entries reported
    assert set(cleaned.keys()) >= {
        "bank", "description", "table_weights", "product_weights",
        "amount_scale", "counterparty_distribution", "collateral_distribution",
    }


def test_save_profile_writes_and_backs_up(tmp_path, schema):
    raw = {"bank": "TestBank", "description": "v1", "table_weights": {"O.D": 2.0}}
    path, warnings = adm.save_profile(tmp_path, "TestBank", raw, schema)
    assert path.exists()
    # Reloads cleanly through the real loader.
    validation = load_profile(path, schema)
    assert validation.profile.bank == "TestBank"
    # Second save creates a .bak of the prior version.
    raw2 = {"bank": "TestBank", "description": "v2", "table_weights": {"O.D": 5.0}}
    adm.save_profile(tmp_path, "TestBank", raw2, schema)
    baks = list(tmp_path.glob("TestBank.json.*.bak"))
    assert len(baks) >= 1
    assert json.loads(path.read_text())["description"] == "v2"


def test_save_profile_bank_name_forced(tmp_path, schema):
    raw = {"bank": "WrongName", "table_weights": {"O.D": 1.0}}
    path, _ = adm.save_profile(tmp_path, "RightName", raw, schema)
    assert json.loads(path.read_text())["bank"] == "RightName"


# --- factors ----------------------------------------------------------------

def test_validate_factors_accepts_shipped():
    raw = adm.read_factors(CONFIG_DIR)
    assert adm.validate_factors(raw) is raw


def test_validate_factors_rejects_bad_haircut():
    bad = {"hqla": {"haircut_by_level": {"L1": 5.0}}}
    with pytest.raises(ConfigError):
        adm.validate_factors(bad)


def test_validate_factors_rejects_bad_inflow_cap():
    bad = {"inflow_rate": {"inflow_cap_pct_of_outflows": 2.0}}
    with pytest.raises(ConfigError):
        adm.validate_factors(bad)


# --- rules ------------------------------------------------------------------

def test_validate_rules_doc_accepts_shipped():
    doc = adm.read_rules_doc(CONFIG_DIR)
    assert adm.validate_rules_doc(doc) is doc


def test_validate_rules_doc_rejects_bad_op():
    doc = {"rules": [{"id": "R", "metric": "approx_lcr", "op": "bogus",
                      "threshold": 1.0, "severity": "high"}]}
    with pytest.raises(ConfigError):
        adm.validate_rules_doc(doc)


def test_validate_rules_doc_rejects_bad_severity_definitions():
    doc = {"rules": [], "severity_definitions": ["not", "a", "dict"]}
    with pytest.raises(ConfigError):
        adm.validate_rules_doc(doc)


def test_validate_rules_doc_requires_rules_array():
    with pytest.raises(ConfigError):
        adm.validate_rules_doc({"no_rules": True})


# --- config round-trips -----------------------------------------------------

def _copy_config(tmp_path) -> Path:
    dst = tmp_path / "cfg"
    dst.mkdir()
    for name in ("factors.json", "rules.json"):
        (dst / name).write_text((CONFIG_DIR / name).read_text(encoding="utf-8"),
                                encoding="utf-8")
    return dst


def test_save_factors_roundtrip_and_backup(tmp_path):
    cfg = _copy_config(tmp_path)
    raw = adm.read_factors(cfg)
    raw["hqla"]["haircut_by_level"]["L2A"] = 0.20
    adm.save_factors(cfg, raw)
    from fr2052a_analytics.config import load_factors
    reloaded = load_factors(cfg)
    assert reloaded["hqla"]["haircut_by_level"]["L2A"] == 0.20
    # Second save creates a backup.
    adm.save_factors(cfg, raw)
    assert list(cfg.glob("factors.json.*.bak"))


def test_save_rules_doc_roundtrip_and_backup(tmp_path):
    cfg = _copy_config(tmp_path)
    doc = adm.read_rules_doc(cfg)
    doc["rules"][0]["threshold"] = 95.0
    adm.save_rules_doc(cfg, doc)
    from fr2052a_analytics.config import load_rules
    reloaded = load_rules(cfg)
    assert reloaded[0]["threshold"] == 95.0
    adm.save_rules_doc(cfg, doc)
    assert list(cfg.glob("rules.json.*.bak"))


# --- generation -------------------------------------------------------------

def test_generate_data_writes_files(tmp_path):
    out = tmp_path / "out"
    paths = adm.generate_data(
        banks=["Wells"], start=date(2026, 1, 1), days=2, fmt="csv",
        out_dir=out, profiles_dir=PROFILES_DIR, schema_path=SCHEMA_PATH, seed=1,
    )
    assert len(paths) == 2
    files = sorted(out.glob("FR2052a_Wells_*.csv"))
    assert len(files) == 2


def test_generate_data_clear_output(tmp_path):
    out = tmp_path / "out"
    adm.generate_data(banks=["Wells"], start=date(2026, 1, 1), days=3, fmt="csv",
                      out_dir=out, profiles_dir=PROFILES_DIR, schema_path=SCHEMA_PATH, seed=1)
    assert len(list(out.glob("FR2052a_*.csv"))) == 3
    # Regenerate with clear_output -> only the new day remains.
    adm.generate_data(banks=["Wells"], start=date(2026, 2, 1), days=1, fmt="csv",
                      out_dir=out, profiles_dir=PROFILES_DIR, schema_path=SCHEMA_PATH,
                      seed=1, clear_output=True)
    remaining = list(out.glob("FR2052a_*.csv"))
    assert len(remaining) == 1
    assert "20260201" in remaining[0].name


def test_generate_data_validation_errors(tmp_path):
    with pytest.raises(ValueError):
        adm.generate_data(banks=[], start=date(2026, 1, 1), days=1, fmt="csv",
                          out_dir=tmp_path, profiles_dir=PROFILES_DIR, schema_path=SCHEMA_PATH)
    with pytest.raises(ValueError):
        adm.generate_data(banks=["Wells"], start=date(2026, 1, 1), days=1, fmt="xml",
                          out_dir=tmp_path, profiles_dir=PROFILES_DIR, schema_path=SCHEMA_PATH)
