"""Tests for the rule-grouped finding helpers in ui_data.

Covers findings_grouped_by_rule, rule_breach_table, and breach_chart_data using
both a controlled hand-built metrics frame (exact aggregation) and an
integration-style run_pipeline over the generated fixture.
"""
from __future__ import annotations

import types
from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics import ui_data
from fr2052a_analytics.config import load_rules
from fr2052a_analytics.metrics import DATE, ENTITY
from fr2052a_analytics.pipeline import run_pipeline
from fr2052a_analytics.rules import Finding, evaluate_rules

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


def _wrap(findings, metrics):
    """Minimal AnalysisResult-like object exposing what ui_data reads."""
    return types.SimpleNamespace(findings=findings, metrics=metrics, forecast=[])


@pytest.fixture(scope="module")
def hand_result():
    """One entity 'X' where approx_lcr breaches LCR_SEVERE (<10) on several days."""
    # approx_lcr values chosen so LCR_SEVERE (<10) fires on all listed days,
    # and LCR_BELOW_REG_MIN (<100) fires on all days too (a medium/high rule).
    dates = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    lcr_vals = [8.0, 2.0, 5.0, 9.0]  # worst (lowest -> highest breach_ratio) = 2.0 on 01-02
    metrics = pd.DataFrame({
        ENTITY: ["X"] * len(dates),
        DATE: pd.to_datetime(dates),
        "approx_lcr": lcr_vals,
    })
    rules = load_rules(CONFIG_DIR)
    findings = evaluate_rules(metrics, rules)
    return _wrap(findings, metrics), dates, lcr_vals


def test_grouped_one_dict_per_rule_no_duplicates(hand_result):
    result, dates, _ = hand_result
    groups = ui_data.findings_grouped_by_rule(result, "X")
    rule_ids = [g["rule_id"] for g in groups]
    assert len(rule_ids) == len(set(rule_ids)), "no duplicate rule rows"

    severe = next(g for g in groups if g["rule_id"] == "LCR_SEVERE")
    # count equals number of breach days for that rule (all 4 days < 10)
    assert severe["count"] == 4
    assert severe["first_date"] <= severe["last_date"]
    assert severe["first_date"] == "2026-01-01"
    assert severe["last_date"] == "2026-01-04"
    # dates sorted
    assert severe["dates"] == sorted(severe["dates"])
    # worst_date corresponds to the max breach_ratio -> lowest lcr value = 2.0 on 01-02
    assert severe["worst_date"] == "2026-01-02"
    assert severe["worst_value"] == pytest.approx(2.0)
    # latest is the max date
    assert severe["latest_date"] == "2026-01-04"
    assert severe["latest_value"] == pytest.approx(9.0)


def test_worst_date_matches_max_breach_ratio(hand_result):
    result, _, _ = hand_result
    groups = ui_data.findings_grouped_by_rule(result, "X")
    frame = ui_data.findings_for_entity(result, "X")
    for g in groups:
        sub = frame[frame["rule_id"] == g["rule_id"]]
        expected = sub.sort_values(["breach_ratio", "date"], ascending=[False, True]).iloc[0]
        assert g["worst_date"] == expected["date"]
        assert g["worst_value"] == pytest.approx(float(expected["value"]))


def test_groups_ordered_by_severity(hand_result):
    result, _, _ = hand_result
    groups = ui_data.findings_grouped_by_rule(result, "X")
    order = {s: i for i, s in enumerate(ui_data.SEVERITY_ORDER)}
    ranks = [order[g["severity"]] for g in groups]
    assert ranks == sorted(ranks), "critical/more-severe groups come first"


def test_groups_ordered_critical_before_medium():
    """Explicit severities: a critical group must sort before a medium group."""
    findings = [
        Finding(entity="X", date="2026-01-02", rule_id="B_MED", severity="medium",
                metric="m", value=1.0, threshold=5.0, message="", breach_ratio=0.5, op="lt"),
        Finding(entity="X", date="2026-01-01", rule_id="A_CRIT", severity="critical",
                metric="m", value=1.0, threshold=5.0, message="", breach_ratio=0.9, op="lt"),
    ]
    metrics = pd.DataFrame({ENTITY: ["X"], DATE: pd.to_datetime(["2026-01-01"]), "m": [1.0]})
    result = _wrap(findings, metrics)
    groups = ui_data.findings_grouped_by_rule(result, "X")
    assert [g["rule_id"] for g in groups] == ["A_CRIT", "B_MED"]


def test_rule_breach_table(hand_result):
    result, dates, _ = hand_result
    bt = ui_data.rule_breach_table(result, "X", "LCR_SEVERE")
    assert list(bt.columns) == ["date", "value", "breach_pct"]
    # rows == count for the rule
    groups = ui_data.findings_grouped_by_rule(result, "X")
    severe = next(g for g in groups if g["rule_id"] == "LCR_SEVERE")
    assert len(bt) == severe["count"]
    # sorted by date
    assert bt["date"].tolist() == sorted(bt["date"].tolist())
    # breach_pct in [0, 100]
    assert (bt["breach_pct"] >= 0).all()
    assert (bt["breach_pct"] <= 100).all()


def test_rule_breach_table_empty(hand_result):
    result, _, _ = hand_result
    bt = ui_data.rule_breach_table(result, "X", "NO_SUCH_RULE")
    assert bt.empty
    assert list(bt.columns) == ["date", "value", "breach_pct"]


def test_breach_chart_data_marks_status_and_selected(hand_result):
    result, dates, _ = hand_result
    breach_dates = ["2026-01-02", "2026-01-03"]
    selected = "2026-01-03"
    cdata = ui_data.breach_chart_data(result, "X", "approx_lcr",
                                      breach_dates=breach_dates, selected_date=selected)
    assert list(cdata.columns) == ["date", "value", "status", "selected"]
    # status == 'breach' exactly for breach_dates
    breach_rows = set(cdata[cdata["status"] == "breach"]["date"])
    assert breach_rows == set(breach_dates)
    # selected True only for selected_date
    sel_rows = cdata[cdata["selected"]]["date"].tolist()
    assert sel_rows == [selected]


def test_breach_chart_data_empty_safe():
    metrics = pd.DataFrame({ENTITY: ["X"], DATE: pd.to_datetime(["2026-01-01"]), "m": [1.0]})
    result = _wrap([], metrics)
    cdata = ui_data.breach_chart_data(result, "X", "no_such_metric", breach_dates=[])
    assert cdata.empty
    assert list(cdata.columns) == ["date", "value", "status", "selected"]


# --- Integration-style test over the generated fixture ----------------------

@pytest.fixture(scope="module")
def pipeline_result(generated_output_dir):
    return run_pipeline(generated_output_dir, CONFIG_DIR, forecast_days=3)


def test_grouped_integration_no_duplicate_rules(pipeline_result):
    for entity in pipeline_result.entities:
        groups = ui_data.findings_grouped_by_rule(pipeline_result, entity)
        rule_ids = [g["rule_id"] for g in groups]
        assert len(rule_ids) == len(set(rule_ids))
        for g in groups:
            # count matches the breach table length
            bt = ui_data.rule_breach_table(pipeline_result, entity, g["rule_id"])
            assert len(bt) == g["count"]
            assert g["first_date"] <= g["last_date"]
            assert g["dates"] == sorted(g["dates"])
            # breach_chart_data is consistent with the group's breach dates
            cdata = ui_data.breach_chart_data(
                pipeline_result, entity, g["metric"], breach_dates=g["dates"],
                selected_date=g["dates"][0] if g["dates"] else None,
            )
            if not cdata.empty:
                marked = set(cdata[cdata["status"] == "breach"]["date"])
                assert marked == set(g["dates"]) & set(cdata["date"])
