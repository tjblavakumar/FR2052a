"""Tests for the declarative rule engine."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics.cli import ConfigError
from fr2052a_analytics.config import load_factors, load_rules
from fr2052a_analytics.loader import load
from fr2052a_analytics.metrics import compute_metrics
from fr2052a_analytics.rules import (
    evaluate_rules,
    findings_to_frame,
    severity_counts,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


@pytest.fixture(scope="session")
def factors():
    return load_factors(CONFIG_DIR)


@pytest.fixture(scope="session")
def shipped_rules():
    return load_rules(CONFIG_DIR)


def _metrics(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    return df


def test_scalar_operators_fire():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "high", "message": "low {value}"}]
    findings = evaluate_rules(m, rules)
    assert len(findings) == 1
    assert findings[0].rule_id == "R1"
    assert findings[0].severity == "high"


def test_scalar_operator_boundary_not_fired():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 100.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "high", "message": "x"}]
    assert evaluate_rules(m, rules) == []


def test_between_and_outside():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "lcr_divergence": 40.0}])
    outside = [{"id": "OUT", "metric": "lcr_divergence", "op": "outside",
                "threshold": [-25.0, 25.0], "severity": "low", "message": "x"}]
    assert len(evaluate_rules(m, outside)) == 1
    between = [{"id": "BET", "metric": "lcr_divergence", "op": "between",
                "threshold": [-25.0, 25.0], "severity": "low", "message": "x"}]
    assert evaluate_rules(m, between) == []


def test_nan_value_skipped():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": float("nan")}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "high", "message": "x"}]
    assert evaluate_rules(m, rules) == []


def test_disabled_rule_skipped():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "high", "message": "x", "enabled": False}]
    assert evaluate_rules(m, rules) == []


def test_absent_metric_skipped():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "no_such_metric", "op": "lt", "threshold": 1.0,
              "severity": "high", "message": "x"}]
    assert evaluate_rules(m, rules) == []


def test_invalid_severity_raises():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "bogus", "message": "x"}]
    with pytest.raises(ConfigError):
        evaluate_rules(m, rules)


def test_unknown_op_raises():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "wat", "threshold": 100.0,
              "severity": "high", "message": "x"}]
    with pytest.raises(ConfigError):
        evaluate_rules(m, rules)


def test_findings_sorted_by_severity():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01",
                   "approx_lcr": 5.0, "stwf_reliance": 0.9}])
    rules = [
        {"id": "MED", "metric": "stwf_reliance", "op": "gt", "threshold": 0.5,
         "severity": "medium", "message": "x"},
        {"id": "CRIT", "metric": "approx_lcr", "op": "lt", "threshold": 10.0,
         "severity": "critical", "message": "x"},
    ]
    findings = evaluate_rules(m, rules)
    assert [f.severity for f in findings] == ["critical", "medium"]


def test_severity_counts_and_frame():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 5.0}])
    rules = [{"id": "CRIT", "metric": "approx_lcr", "op": "lt", "threshold": 10.0,
              "severity": "critical", "message": "sev {value:.1f}"}]
    findings = evaluate_rules(m, rules)
    counts = severity_counts(findings)
    assert counts["critical"] == 1
    frame = findings_to_frame(findings)
    assert list(frame.columns) == ["entity", "date", "rule_id", "severity",
                                    "metric", "value", "threshold", "message",
                                    "description", "rationale", "recommended_action",
                                    "breach_ratio", "op"]
    assert "sev 5.0" in frame.iloc[0]["message"]


def test_shipped_rules_on_generated_data(generated_output_dir, factors, shipped_rules):
    result = load(generated_output_dir)
    m = compute_metrics(result.frame, factors)
    findings = evaluate_rules(m, shipped_rules)
    # Synthetic data has low approx_lcr, so LCR rules should fire.
    assert len(findings) > 0
    assert any(f.rule_id in ("LCR_BELOW_REG_MIN", "LCR_SEVERE") for f in findings)
    # Every finding references a real entity/date and known severity.
    for f in findings:
        assert f.entity in {"Wells", "BoFA", "Chase"}
        assert f.severity in ("info", "low", "medium", "high", "critical")
