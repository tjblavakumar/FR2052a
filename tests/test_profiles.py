"""Tests for bank profile loading, validation, and weighted generation."""
from __future__ import annotations

import random
from collections import Counter
from datetime import date

import pytest

from fr2052a_mockgen.profiles import (
    ProfileError,
    load_bank_profile,
    validate_profile,
)
from fr2052a_mockgen.report_builder import ReportBuilder


def test_valid_profile_kept(schema, sample_profile_raw):
    v = validate_profile(sample_profile_raw, schema)
    assert v.profile.bank == "TestBank"
    assert v.profile.table_weights["O.D"] == 4.0
    assert v.profile.product_weights["O.D.1"] == 5.0
    assert v.warnings == []


def test_invalid_references_dropped(schema):
    raw = {
        "bank": "X",
        "table_weights": {"O.D": 2.0, "BADPREFIX": 1.0},
        "product_weights": {"O.D.1": 1.0, "Z.Z.9": 1.0},
        "counterparty_distribution": {"O.D": {"Retail": 1.0, "FakeCP": 1.0}},
        "collateral_distribution": {"O.S": {"A-1-Q": 1.0, "NOPE": 1.0}},
    }
    v = validate_profile(raw, schema)
    assert "BADPREFIX" not in v.profile.table_weights
    assert "Z.Z.9" not in v.profile.product_weights
    assert "FakeCP" not in v.profile.counterparty_distribution["O.D"]
    assert "NOPE" not in v.profile.collateral_distribution["O.S"]
    assert len(v.warnings) == 4


def test_missing_bank_field(schema):
    with pytest.raises(ProfileError, match="missing required 'bank'"):
        validate_profile({"table_weights": {}}, schema)


def test_load_bank_profile_missing(schema, tmp_path):
    with pytest.raises(ProfileError, match="No profile found for bank"):
        load_bank_profile(tmp_path, "Nonexistent", schema)


def test_load_bank_profile_from_dir(schema, profiles_dir):
    v = load_bank_profile(profiles_dir, "TestBank", schema)
    assert v.profile.bank == "TestBank"


def test_committed_profiles_load_clean(schema):
    for bank in ["Wells", "BoFA", "USWest", "Chase", "CapOne"]:
        v = load_bank_profile("bank_profiles", bank, schema)
        assert v.warnings == []
        assert v.profile.bank == bank


def test_weighted_row_counts(schema, sample_profile_raw):
    profile = validate_profile(sample_profile_raw, schema).profile
    builder = ReportBuilder(schema, random.Random(5), profile=profile)
    rows = builder.build("TestBank", date(2022, 1, 1))
    counts = Counter(r["SubTable"] for r in rows)
    # O.D weighted 4.0, S.DC weighted 0.2 -> deposits should dominate derivatives
    assert counts["Deposits"] > counts["Derivatives & Collateral"]


def test_weighted_counterparty(schema, sample_profile_raw):
    profile = validate_profile(sample_profile_raw, schema).profile
    builder = ReportBuilder(schema, random.Random(5), profile=profile)
    rows = builder.build("TestBank", date(2022, 1, 1))
    od_cp = Counter(
        r.get("Counterparty") for r in rows if r["SubTable"] == "Deposits" and r.get("Counterparty")
    )
    # Only Retail / Small Business allowed by the profile distribution
    assert set(od_cp) <= {"Retail", "Small Business"}
    assert od_cp["Retail"] > od_cp["Small Business"]


def test_profile_deterministic(schema, sample_profile_raw):
    profile = validate_profile(sample_profile_raw, schema).profile
    r1 = ReportBuilder(schema, random.Random(9), profile=profile).build("T", date(2022, 1, 1))
    r2 = ReportBuilder(schema, random.Random(9), profile=profile).build("T", date(2022, 1, 1))
    assert r1 == r2


def test_no_profile_still_valid(schema):
    builder = ReportBuilder(schema, random.Random(3))
    rows = builder.build("Any", date(2022, 1, 1))
    assert len(rows) > 0
