"""Tests for the CSV/JSON writer and file naming."""
from __future__ import annotations

import json
import random
from datetime import date

import pandas as pd
import pytest

from fr2052a_mockgen.report_builder import ReportBuilder
from fr2052a_mockgen.writer import file_name, write_report


def _rows(schema):
    return ReportBuilder(schema, random.Random(3)).build("Wells", date(2022, 1, 1))


def test_file_name():
    assert file_name("Wells", date(2022, 1, 1), "csv") == "FR2052a_Wells_20220101.csv"
    assert file_name("BoFA", date(2022, 12, 31), "json") == "FR2052a_BoFA_20221231.json"


def test_csv_written_with_leading_columns(schema, tmp_path):
    rows = _rows(schema)
    path = write_report(rows, "Wells", date(2022, 1, 1), tmp_path, "csv")
    assert path.exists()
    assert path.name == "FR2052a_Wells_20220101.csv"
    df = pd.read_csv(path)
    assert list(df.columns)[:5] == ["Table", "SubTable", "ReportingEntity", "ReportDate", "Product"]
    assert len(df) == len(rows)


def test_json_round_trips(schema, tmp_path):
    rows = _rows(schema)
    path = write_report(rows, "Chase", date(2022, 2, 2), tmp_path, "json")
    assert path.name == "FR2052a_Chase_20220202.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["report"] == "FR 2052a"
    assert payload["reportingEntity"] == "Chase"
    assert payload["reportDate"] == "2022-02-02"
    assert payload["rowCount"] == len(rows)
    assert len(payload["rows"]) == len(rows)


def test_creates_output_dir(schema, tmp_path):
    rows = _rows(schema)
    nested = tmp_path / "a" / "b"
    path = write_report(rows, "Wells", date(2022, 1, 1), nested, "csv")
    assert path.exists()


def test_invalid_format(schema, tmp_path):
    rows = _rows(schema)
    with pytest.raises(ValueError, match="Unsupported format"):
        write_report(rows, "Wells", date(2022, 1, 1), tmp_path, "xml")
