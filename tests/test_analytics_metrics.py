"""Tests for the core liquidity metrics engine."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics.config import load_factors
from fr2052a_analytics.loader import load
from fr2052a_analytics.metrics import (
    compute_core_metrics,
    compute_hqla,
    compute_outflows,
    hqla_level,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


@pytest.fixture(scope="session")
def factors():
    return load_factors(CONFIG_DIR)


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    return df


def test_hqla_level_classification(factors):
    assert hqla_level("A-1-Q", factors) == "L1"
    assert hqla_level("G-2-Q", factors) == "L1"
    assert hqla_level("S-1-Q", factors) == "L2A"
    assert hqla_level("E-2-Q", factors) == "L2B"
    # Non-HQLA: missing -Q suffix, or non-mapped class.
    assert hqla_level("A-2", factors) is None
    assert hqla_level("P-1", factors) is None
    assert hqla_level("", factors) is None


def test_hqla_haircuts(factors):
    rows = [
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "A-1-Q", "MarketValue": 1000.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "S-1-Q", "MarketValue": 1000.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "A-2", "MarketValue": 5000.0},
    ]
    hqla = compute_hqla(_frame(rows), factors)
    # L1 = 1000 (0% haircut); L2A = 1000 * 0.85 = 850; non-HQLA A-2 excluded.
    # L2 (850) < 40% cap of total(1850)=740? 850 > 740 -> capped to 740.
    row = hqla.iloc[0]
    assert row["hqla_l1"] == 1000.0
    assert abs(row["hqla_l2a"] - 850.0) < 1e-6
    # stock = L1 + min(L2, 40%*total)
    total_pre = 1000.0 + 850.0
    expected = 1000.0 + min(850.0, 0.40 * total_pre)
    assert abs(row["hqla_stock"] - expected) < 1e-6


def test_outflows_deposit_runoff(factors):
    rows = [
        # Insured retail stable deposit: low runoff (0.03).
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Deposits", "Product": "O.D.1", "Counterparty": "Retail",
         "Insured": "Y", "MaturityAmount": 1000.0},
        # Non-operational financial: full runoff (1.00).
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Deposits", "Product": "O.D.6", "Counterparty": "Bank",
         "Insured": "N", "MaturityAmount": 1000.0},
    ]
    out = compute_outflows(_frame(rows), factors)
    # 1000*0.03 + 1000*1.00 = 1030
    assert abs(out.iloc[0]["stress_outflows"] - 1030.0) < 1e-6


def test_core_metrics_lcr_and_cap(factors):
    rows = [
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "A-1-Q", "MarketValue": 1000.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Deposits", "Product": "O.D.6", "Counterparty": "Bank",
         "MaturityAmount": 1000.0},
        # A big unsecured inflow that should be capped at 75% of outflows.
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Unsecured", "Product": "I.U.1", "MaturityAmount": 100000.0},
    ]
    m = compute_core_metrics(_frame(rows), factors)
    row = m.iloc[0]
    assert row["hqla_stock"] == 1000.0
    assert row["stress_outflows"] == 1000.0
    # inflow capped to 0.75 * 1000 = 750; net = 1000 - 750 = 250
    assert abs(row["stress_inflows"] - 750.0) < 1e-6
    assert abs(row["net_outflows"] - 250.0) < 1e-6
    # approx_lcr = 100 * 1000 / 250 = 400%
    assert abs(row["approx_lcr"] - 400.0) < 1e-6


def test_core_metrics_zero_outflows_lcr_na(factors):
    rows = [
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "A-1-Q", "MarketValue": 500.0},
    ]
    m = compute_core_metrics(_frame(rows), factors)
    assert pd.isna(m.iloc[0]["approx_lcr"])


def test_core_metrics_on_generated_data(generated_output_dir, factors):
    result = load(generated_output_dir)
    m = compute_core_metrics(result.frame, factors)
    # One row per (entity, date): 3 banks x 6 days = 18.
    assert len(m) == 18
    assert {"hqla_stock", "stress_outflows", "net_outflows", "approx_lcr",
            "reported_lcr", "reported_nsfr", "lcr_divergence"}.issubset(m.columns)
    # HQLA and outflows should be positive for realistic data.
    assert (m["hqla_stock"] > 0).all()
    assert (m["stress_outflows"] > 0).all()


# --- Derived indicators + business-line breakdown (Task 4) ------------------

from fr2052a_analytics.metrics import (  # noqa: E402
    compute_business_line_breakdown,
    compute_derived_indicators,
    compute_metrics,
)


def test_derived_stwf_and_deposit_shares(factors):
    rows = [
        # Wholesale: 1000 short-term (Day 5) + 3000 long-term (>5 Yr) = 25% STWF.
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Wholesale", "Product": "O.W.9", "MaturityAmount": 1000.0,
         "MaturityBucket": "Day 5"},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Wholesale", "Product": "O.W.11", "MaturityAmount": 3000.0,
         "MaturityBucket": ">5 Yr"},
        # Deposits: 800 insured + 200 uninsured = 80% insured share.
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Deposits", "Product": "O.D.1", "Counterparty": "Retail",
         "Insured": "Y", "MaturityAmount": 800.0, "MaturityBucket": "Open"},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Deposits", "Product": "O.D.1", "Counterparty": "Retail",
         "Insured": "N", "MaturityAmount": 200.0, "MaturityBucket": "Open"},
    ]
    d = compute_derived_indicators(_frame(rows), factors)
    row = d.iloc[0]
    assert abs(row["stwf_reliance"] - 0.25) < 1e-6
    assert abs(row["insured_deposit_share"] - 0.80) < 1e-6


def test_derived_intercompany_trapped_share(factors):
    rows = [
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Supplemental",
         "SubTable": "Liquidity Risk Measurement", "Product": "S.L.1", "MarketValue": 300.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Supplemental",
         "SubTable": "Liquidity Risk Measurement", "Product": "S.L.7", "MarketValue": 300.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Supplemental",
         "SubTable": "Liquidity Risk Measurement", "Product": "S.L.2", "MarketValue": 200.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Supplemental",
         "SubTable": "Liquidity Risk Measurement", "Product": "S.L.8", "MarketValue": 200.0},
    ]
    d = compute_derived_indicators(_frame(rows), factors)
    # trapped 600 / (600 + 400) = 0.6
    assert abs(d.iloc[0]["intercompany_trapped_share"] - 0.6) < 1e-6


def test_compute_metrics_downgrade_drain_to_hqla(factors):
    rows = [
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Inflows",
         "SubTable": "Assets", "Product": "I.A.1", "CollateralClass": "A-1-Q", "MarketValue": 1000.0},
        {"ReportingEntity": "X", "ReportDate": "2026-01-01", "Table": "Outflows",
         "SubTable": "Other", "Product": "O.O.13", "MaturityAmount": 500.0},
    ]
    m = compute_metrics(_frame(rows), factors)
    # downgrade drain 500 / hqla 1000 = 0.5
    assert abs(m.iloc[0]["downgrade_drain_to_hqla"] - 0.5) < 1e-6


def test_business_line_breakdown_rolls_up(generated_output_dir, factors):
    result = load(generated_output_dir)
    bl = compute_business_line_breakdown(result.frame, factors)
    assert {"BusinessLine", "hqla_stock", "stress_outflows"}.issubset(bl.columns)
    # Business-line outflows should roll up to entity totals from compute_metrics.
    m = compute_metrics(result.frame, factors)
    for (entity, date_), grp in bl.groupby(["ReportingEntity", "ReportDate"]):
        entity_row = m[(m.ReportingEntity == entity) & (m.ReportDate == date_)]
        if entity_row.empty:
            continue
        assert abs(grp["stress_outflows"].sum() - entity_row.iloc[0]["stress_outflows"]) < 1.0


def test_compute_metrics_on_generated_data(generated_output_dir, factors):
    result = load(generated_output_dir)
    m = compute_metrics(result.frame, factors)
    assert len(m) == 18
    expected = {"stwf_reliance", "insured_deposit_share", "secured_rollover_share",
                "intercompany_trapped_share", "downgrade_drain", "downgrade_drain_to_hqla"}
    assert expected.issubset(m.columns)
    # Shares are bounded [0, 1].
    for col in ("insured_deposit_share", "intercompany_trapped_share", "stwf_reliance",
                "secured_rollover_share"):
        assert (m[col] >= -1e-9).all() and (m[col] <= 1.0 + 1e-9).all()
