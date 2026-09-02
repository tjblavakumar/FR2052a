"""Tests for the Streamlit-free UI data-preparation helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from fr2052a_analytics import ui_data
from fr2052a_analytics.pipeline import run_pipeline

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


@pytest.fixture(scope="module")
def result(generated_output_dir):
    return run_pipeline(generated_output_dir, CONFIG_DIR, forecast_days=3)


def test_available_metrics_includes_core(result):
    metrics = ui_data.available_metrics(result)
    assert "approx_lcr" in metrics
    assert "hqla_stock" in metrics
    # Identity columns excluded.
    assert "ReportingEntity" not in metrics
    assert "ReportDate" not in metrics


def test_metric_timeseries(result):
    ts = ui_data.metric_timeseries(result.metrics, "Wells", "approx_lcr")
    assert list(ts.columns) == ["ReportDate", "value"]
    # 6 days of history for the generated fixture.
    assert len(ts) <= 6 and len(ts) > 0


def test_metric_timeseries_absent_metric(result):
    ts = ui_data.metric_timeseries(result.metrics, "Wells", "no_such_metric")
    assert ts.empty


def test_metric_with_forecast_has_both_series(result):
    df = ui_data.metric_with_forecast(result, "Wells", "approx_lcr")
    series = set(df["series"].unique())
    assert "actual" in series
    # forecast_days=3 with 6 days of history -> forecast series present.
    assert "forecast (experimental)" in series


def test_findings_for_entity_sorted(result):
    f = ui_data.findings_for_entity(result, "BoFA")
    if not f.empty:
        assert (f["entity"] == "BoFA").all()
        order = {s: i for i, s in enumerate(ui_data.SEVERITY_ORDER)}
        ranks = [order[s] for s in f["severity"]]
        assert ranks == sorted(ranks)


def test_peers_for_metric(result):
    peers = ui_data.peers_for_metric(result, "approx_lcr")
    if not peers.empty:
        assert (peers["metric"] == "approx_lcr").all()
        # Sorted descending by percentile rank.
        ranks = peers["percentile_rank"].tolist()
        assert ranks == sorted(ranks, reverse=True)


def test_business_line_snapshot(result):
    bl = ui_data.business_line_snapshot(result, "Chase")
    assert {"BusinessLine", "hqla_stock", "stress_outflows"}.issubset(bl.columns) or bl.empty


def test_severity_summary_frame(result):
    frame = ui_data.severity_summary_frame(result)
    assert list(frame["severity"]) == ui_data.SEVERITY_ORDER
    assert frame["count"].sum() == len(result.findings)


@pytest.mark.skipif(importlib.util.find_spec("streamlit") is None,
                    reason="streamlit not installed (optional [ui] dependency)")
def test_app_module_imports():
    """If streamlit is installed, the app module should import and expose main()."""
    from fr2052a_analytics import app
    assert callable(app.main)


def test_severity_color_scale_matches_colors():
    from fr2052a_analytics import ui_data
    domain, range_ = ui_data.severity_color_scale()
    assert domain == ui_data.SEVERITY_ORDER
    assert range_ == [ui_data.SEVERITY_COLORS[s] for s in ui_data.SEVERITY_ORDER]
    # critical must be the dark red, not a default blue
    assert dict(zip(domain, range_))["critical"] == "#8B0000"
    # custom order is honored
    d2, r2 = ui_data.severity_color_scale(["high", "low"])
    assert d2 == ["high", "low"]
    assert r2 == [ui_data.SEVERITY_COLORS["high"], ui_data.SEVERITY_COLORS["low"]]
