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
