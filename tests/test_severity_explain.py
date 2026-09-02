"""Tests for the explainable-severity enhancement (rules metadata + UI helpers)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics import ui_data
from fr2052a_analytics.pipeline import run_pipeline
from fr2052a_analytics.rules import (
    Finding,
    compute_breach_ratio,
    evaluate_rules,
    findings_to_frame,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


def _metrics(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    return df


# --- rules -----------------------------------------------------------------

def test_compute_breach_ratio_scalar_lt():
    assert compute_breach_ratio("lt", 8.5, 100.0) == pytest.approx(0.915, abs=1e-3)


def test_compute_breach_ratio_scalar_gt():
    assert compute_breach_ratio("gt", 1.5, 1.0) == pytest.approx(0.5, abs=1e-3)


def test_compute_breach_ratio_outside():
    assert compute_breach_ratio("outside", 40.0, [-25.0, 25.0]) == pytest.approx(0.6, abs=1e-3)


def test_compute_breach_ratio_between_is_zero():
    assert compute_breach_ratio("between", 10.0, [-25.0, 25.0]) == 0.0


def test_compute_breach_ratio_zero_threshold():
    assert compute_breach_ratio("lt", 5.0, 0.0) == pytest.approx(5.0, abs=1e-9)


def test_evaluate_rules_threads_metadata():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{
        "id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
        "severity": "high", "message": "low {value}",
        "description": "desc text", "rationale": "why text",
        "recommended_action": "do this",
    }]
    findings = evaluate_rules(m, rules)
    assert len(findings) == 1
    fnd = findings[0]
    assert fnd.description == "desc text"
    assert fnd.rationale == "why text"
    assert fnd.recommended_action == "do this"
    assert fnd.op == "lt"
    assert fnd.breach_ratio > 0


def test_findings_to_frame_includes_new_columns():
    m = _metrics([{"ReportingEntity": "X", "ReportDate": "2026-01-01", "approx_lcr": 50.0}])
    rules = [{"id": "R1", "metric": "approx_lcr", "op": "lt", "threshold": 100.0,
              "severity": "high", "message": "x"}]
    frame = findings_to_frame(evaluate_rules(m, rules))
    for col in ("description", "rationale", "recommended_action", "breach_ratio", "op"):
        assert col in frame.columns


def test_finding_backward_compatible_construction():
    fnd = Finding("X", "2026-01-01", "R1", "high", "approx_lcr", 50.0, 100.0, "msg")
    assert fnd.description == ""
    assert fnd.rationale == ""
    assert fnd.recommended_action == ""
    assert fnd.breach_ratio == 0.0
    assert fnd.op == ""


# --- ui_data ---------------------------------------------------------------

def test_gauge_data_percent_and_color():
    fnd = Finding("X", "2026-01-01", "R1", "high", "approx_lcr", 50.0, 100.0, "msg",
                  breach_ratio=0.5)
    g = ui_data.gauge_data(fnd)
    assert g["percent"] == 50.0
    assert g["color"] == ui_data.SEVERITY_COLORS["high"]


def test_gauge_data_caps_at_100():
    fnd = Finding("X", "2026-01-01", "R1", "critical", "approx_lcr", 1.0, 100.0, "msg",
                  breach_ratio=3.0)
    g = ui_data.gauge_data(fnd)
    assert g["percent"] == 100.0


def test_severity_definitions_fallback_and_passthrough():
    fallback = ui_data.severity_definitions(None)
    assert len(fallback) == 5
    assert set(fallback) == {"critical", "high", "medium", "low", "info"}
    passed = ui_data.severity_definitions({"critical": "x"})
    assert passed == {"critical": "x"}


# --- finding_detail via real pipeline --------------------------------------

@pytest.fixture(scope="module")
def result(generated_output_dir):
    return run_pipeline(generated_output_dir, CONFIG_DIR, forecast_days=3)


def test_finding_detail_returns_dict(result):
    assert len(result.findings) > 0
    detail = ui_data.finding_detail(result, 0)
    assert "rationale" in detail


def test_finding_detail_out_of_range(result):
    assert ui_data.finding_detail(result, len(result.findings)) == {}
