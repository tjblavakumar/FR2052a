"""Shared pytest fixtures for the FR 2052a mock generator tests."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from fr2052a_mockgen.schema_loader import load_schema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "fr2052a_schema.json"


@pytest.fixture(scope="session")
def schema():
    return load_schema(SCHEMA_PATH)


@pytest.fixture
def rng():
    return random.Random(20240101)


@pytest.fixture
def sample_profile_raw():
    """A small, valid profile used across profile/generation tests."""
    return {
        "bank": "TestBank",
        "description": "deposit heavy test bank",
        "table_weights": {"O.D": 4.0, "S.DC": 0.2},
        "product_weights": {"O.D.1": 5.0},
        "amount_scale": {"O.D": 3.0},
        "counterparty_distribution": {"O.D": {"Retail": 8.0, "Small Business": 2.0}},
        "collateral_distribution": {"O.S": {"A-1-Q": 5.0, "G-2-Q": 2.0}},
    }


@pytest.fixture
def profiles_dir(tmp_path, sample_profile_raw):
    """A temp profiles directory containing one profile for 'TestBank'."""
    import json

    (tmp_path / "TestBank.json").write_text(
        json.dumps(sample_profile_raw), encoding="utf-8"
    )
    return tmp_path


# --- Analytics (phase 2) fixtures -------------------------------------------

@pytest.fixture
def csv_output_dir(tmp_path):
    """A temp dir with two hand-written phase-1 CSV files (2 banks x 1 day)."""
    d = tmp_path / "csv_out"
    d.mkdir()
    header = "Table,SubTable,ReportingEntity,ReportDate,Product,MarketValue,MaturityAmount,BusinessLine\n"
    (d / "FR2052a_Alpha_20260101.csv").write_text(
        header
        + "Inflows,Assets,Alpha,2026-01-01,I.A.1,1000.0,,Markets\n"
        + "Outflows,Deposits,Alpha,2026-01-01,O.D.1,,500.0,Retail\n",
        encoding="utf-8",
    )
    (d / "FR2052a_Beta_20260101.csv").write_text(
        header
        + "Inflows,Assets,Beta,2026-01-01,I.A.1,2000.0,,Markets\n"
        + "Outflows,Deposits,Beta,2026-01-01,O.D.1,,900.0,Retail\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def json_output_dir(tmp_path):
    """A temp dir with one phase-1 JSON file (drops empty keys per row)."""
    import json as _json

    d = tmp_path / "json_out"
    d.mkdir()
    payload = {
        "report": "FR 2052a",
        "reportingEntity": "Alpha",
        "reportDate": "2026-01-01",
        "rowCount": 2,
        "rows": [
            {"Table": "Inflows", "SubTable": "Assets", "ReportingEntity": "Alpha",
             "ReportDate": "2026-01-01", "Product": "I.A.1", "MarketValue": 1000.0,
             "BusinessLine": "Markets"},
            {"Table": "Outflows", "SubTable": "Deposits", "ReportingEntity": "Alpha",
             "ReportDate": "2026-01-01", "Product": "O.D.1", "MaturityAmount": 500.0,
             "BusinessLine": "Retail"},
        ],
    }
    (d / "FR2052a_Alpha_20260101.json").write_text(_json.dumps(payload), encoding="utf-8")
    return d


@pytest.fixture(scope="session")
def generated_output_dir(tmp_path_factory):
    """Run the phase-1 generator to produce a real multi-day dataset.

    Used by metrics/analytics/end-to-end tests that need realistic, internally
    consistent data across several banks and days.
    """
    import random
    from datetime import date, timedelta

    from fr2052a_mockgen.profiles import load_bank_profile
    from fr2052a_mockgen.report_builder import ReportBuilder
    from fr2052a_mockgen.schema_loader import load_schema
    from fr2052a_mockgen.writer import write_report

    root = Path(__file__).resolve().parents[1]
    schema = load_schema(root / "schema" / "fr2052a_schema.json")
    profiles_dir = root / "bank_profiles"
    out = tmp_path_factory.mktemp("gen_out")

    banks = ["Wells", "BoFA", "Chase"]
    start = date(2026, 1, 1)
    days = 6
    for i, bank in enumerate(banks):
        validation = load_bank_profile(profiles_dir, bank, schema)
        builder = ReportBuilder(schema, random.Random(100 + i), profile=validation.profile)
        for offset in range(days):
            rd = start + timedelta(days=offset)
            rows = builder.build(bank, rd)
            write_report(rows, bank, rd, out, "csv", report_name=schema.report)
    return out
