"""Tests for the analytics loader (phase-1 file normalization)."""
from __future__ import annotations

import pandas as pd
import pytest

from fr2052a_analytics.cli import InputError
from fr2052a_analytics.loader import (
    KEY_COLUMNS,
    discover_files,
    load,
    parse_filename,
)


def test_parse_filename_valid():
    parsed = parse_filename("FR2052a_Wells_20260101.csv")
    assert parsed is not None
    bank, dt = parsed
    assert bank == "Wells"
    assert dt == pd.Timestamp("2026-01-01")


def test_parse_filename_json_ext():
    parsed = parse_filename("FR2052a_CapOne_20260205.json")
    assert parsed is not None
    assert parsed[0] == "CapOne"


def test_parse_filename_rejects_other():
    assert parse_filename("notes.txt") is None
    assert parse_filename("FR2052a_Bank.csv") is None
    assert parse_filename("FR2052a_Bank_2026.csv") is None


def test_discover_missing_dir(tmp_path):
    with pytest.raises(InputError):
        discover_files(tmp_path / "nope")


def test_discover_filters_by_bank(csv_output_dir):
    files = discover_files(csv_output_dir, banks=["Alpha"])
    assert len(files) == 1
    assert "Alpha" in files[0].name


def test_load_csv(csv_output_dir):
    result = load(csv_output_dir)
    df = result.frame
    for col in KEY_COLUMNS:
        assert col in df.columns
    assert set(result.entities) == {"Alpha", "Beta"}
    assert df["ReportDate"].dtype.kind == "M"  # datetime64
    # MarketValue coerced to numeric; blank -> NaN.
    assert pd.api.types.is_numeric_dtype(df["MarketValue"])
    alpha_asset = df[(df.ReportingEntity == "Alpha") & (df.Product == "I.A.1")]
    assert float(alpha_asset["MarketValue"].iloc[0]) == 1000.0


def test_load_json(json_output_dir):
    result = load(json_output_dir)
    df = result.frame
    assert set(result.entities) == {"Alpha"}
    # JSON rows drop empty keys, but union of columns still present & filled.
    assert "MaturityAmount" in df.columns
    assert pd.api.types.is_numeric_dtype(df["MarketValue"])


def test_csv_and_json_same_shape(csv_output_dir, json_output_dir):
    """Alpha's rows should normalize to comparable columns regardless of format."""
    csv_alpha = load(csv_output_dir, banks=["Alpha"]).frame
    json_alpha = load(json_output_dir, banks=["Alpha"]).frame
    common = set(KEY_COLUMNS) | {"MarketValue", "MaturityAmount", "BusinessLine"}
    assert common.issubset(set(csv_alpha.columns))
    assert common.issubset(set(json_alpha.columns))
    # Same number of Alpha rows (2) from each source.
    assert len(csv_alpha) == 2
    assert len(json_alpha) == 2


def test_load_empty_dir_raises(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(InputError):
        load(d)


def test_load_generated_dataset(generated_output_dir):
    result = load(generated_output_dir)
    df = result.frame
    assert set(result.entities) == {"Wells", "BoFA", "Chase"}
    assert len(result.dates) == 6
    # Every row carries identity columns.
    assert df["ReportingEntity"].ne("").all()
    assert df["Table"].ne("").all()
    assert df["SourceFile"].ne("").all()


def test_discover_entities(csv_output_dir):
    from fr2052a_analytics.loader import discover_entities
    ents = discover_entities(csv_output_dir)
    assert ents == ["Alpha", "Beta"]


def test_discover_entities_missing_dir(tmp_path):
    from fr2052a_analytics.loader import discover_entities
    assert discover_entities(tmp_path / "nope") == []


def test_discover_entities_empty_dir(tmp_path):
    from fr2052a_analytics.loader import discover_entities
    d = tmp_path / "empty"; d.mkdir()
    assert discover_entities(d) == []
