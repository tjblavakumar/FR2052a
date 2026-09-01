"""Tests for peer comparison and the experimental forecast."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics.config import load_factors
from fr2052a_analytics.forecast import forecast_metrics, forecast_to_frame
from fr2052a_analytics.loader import load
from fr2052a_analytics.metrics import compute_metrics
from fr2052a_analytics.peer import compare_peers, peers_to_frame

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


@pytest.fixture(scope="session")
def factors():
    return load_factors(CONFIG_DIR)


def _multi_entity(values_by_entity: dict[str, float], date: str = "2026-01-01",
                  metric: str = "approx_lcr") -> pd.DataFrame:
    rows = [{"ReportingEntity": e, "ReportDate": date, metric: v}
            for e, v in values_by_entity.items()]
    df = pd.DataFrame(rows)
    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    return df


# --- Peer comparison --------------------------------------------------------

def test_peer_percentile_and_median():
    m = _multi_entity({"A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0})
    comps = compare_peers(m, metric_names=["approx_lcr"])
    by_entity = {c.entity: c for c in comps}
    assert by_entity["A"].peer_median == 25.0
    assert by_entity["A"].peer_count == 4
    # A is the minimum -> percentile rank 25 (1 of 4 at-or-below).
    assert by_entity["A"].percentile_rank == 25.0
    assert by_entity["D"].percentile_rank == 100.0


def test_peer_requires_two_entities():
    m = _multi_entity({"A": 10.0})
    assert compare_peers(m, metric_names=["approx_lcr"]) == []


def test_peer_filter_by_peers_list():
    m = _multi_entity({"A": 10.0, "B": 20.0, "C": 30.0})
    comps = compare_peers(m, peers=["A", "B"], metric_names=["approx_lcr"])
    assert {c.entity for c in comps} == {"A", "B"}
    assert all(c.peer_count == 2 for c in comps)


def test_peer_missing_date_returns_empty():
    m = _multi_entity({"A": 10.0, "B": 20.0})
    assert compare_peers(m, on_date="2030-12-31", metric_names=["approx_lcr"]) == []


def test_peers_to_frame_columns():
    m = _multi_entity({"A": 10.0, "B": 20.0})
    frame = peers_to_frame(compare_peers(m, metric_names=["approx_lcr"]))
    assert "percentile_rank" in frame.columns and "peer_median" in frame.columns


# --- Forecast ---------------------------------------------------------------

def _series(values: list[float], entity: str = "X", metric: str = "approx_lcr") -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"ReportingEntity": entity, "ReportDate": dates, metric: values})


def test_forecast_linear_projection():
    df = _series([100, 110, 120, 130])  # +10/day
    pts = forecast_metrics(df, horizon_days=2, metric_names=["approx_lcr"])
    assert len(pts) == 2
    # Next two days should continue the trend: ~140, ~150.
    assert abs(pts[0].value - 140.0) < 1e-6
    assert abs(pts[1].value - 150.0) < 1e-6
    assert all(p.experimental for p in pts)
    assert pts[0].date == "2026-01-05"


def test_forecast_horizon_zero_empty():
    df = _series([100, 110, 120])
    assert forecast_metrics(df, horizon_days=0, metric_names=["approx_lcr"]) == []


def test_forecast_short_series_guard():
    df = _series([100, 110])  # 2 points < min_points (3)
    assert forecast_metrics(df, horizon_days=3, metric_names=["approx_lcr"]) == []


def test_forecast_moving_average_method():
    df = _series([10, 20, 30, 40])
    factors = {"analytics": {"forecast": {"method": "moving_average",
                                          "moving_average_window": 2, "min_points": 3}}}
    pts = forecast_metrics(df, horizon_days=2, factors=factors, metric_names=["approx_lcr"])
    # MA of last 2 = (30+40)/2 = 35 for all horizon points.
    assert all(abs(p.value - 35.0) < 1e-6 for p in pts)
    assert all(p.method == "moving_average" for p in pts)


def test_forecast_to_frame_columns():
    df = _series([100, 110, 120])
    frame = forecast_to_frame(forecast_metrics(df, horizon_days=1, metric_names=["approx_lcr"]))
    assert list(frame.columns) == ["entity", "metric", "date", "value", "method", "experimental"]


# --- On generated data ------------------------------------------------------

def test_on_generated_data(generated_output_dir, factors):
    result = load(generated_output_dir)
    m = compute_metrics(result.frame, factors)
    comps = compare_peers(m, factors=factors)
    assert len(comps) > 0
    assert {c.entity for c in comps} == {"Wells", "BoFA", "Chase"}
    pts = forecast_metrics(m, horizon_days=3, factors=factors)
    assert len(pts) > 0
    assert all(p.experimental for p in pts)
