"""Tests for trend analysis and statistical anomaly detection."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fr2052a_analytics.anomaly import anomalies_to_frame, detect_anomalies
from fr2052a_analytics.config import load_factors
from fr2052a_analytics.loader import load
from fr2052a_analytics.metrics import compute_metrics
from fr2052a_analytics.trend import compute_trends, trends_to_frame

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


@pytest.fixture(scope="session")
def factors():
    return load_factors(CONFIG_DIR)


def _series(entity: str, metric: str, values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.DataFrame({
        "ReportingEntity": entity,
        "ReportDate": dates,
        metric: values,
    })


def test_trend_rising_series():
    df = _series("X", "approx_lcr", [100, 110, 120, 130, 140])
    trends = compute_trends(df, metric_names=["approx_lcr"])
    assert len(trends) == 1
    t = trends[0]
    assert t.direction == "up"
    assert abs(t.slope_per_day - 10.0) < 1e-6
    assert t.total_change == 40.0
    assert t.latest_delta == 10.0
    assert t.first_value == 100.0 and t.last_value == 140.0


def test_trend_falling_and_flat():
    down = compute_trends(_series("X", "m", [50, 40, 30]), metric_names=["m"])[0]
    assert down.direction == "down"
    assert down.slope_per_day < 0
    flat = compute_trends(_series("Y", "m", [10, 10, 10]), metric_names=["m"])[0]
    assert flat.direction == "flat"
    assert flat.slope_per_day == 0.0


def test_trend_single_point():
    t = compute_trends(_series("X", "m", [42.0]), metric_names=["m"])[0]
    assert t.n_points == 1
    assert t.slope_per_day == 0.0
    assert t.total_change == 0.0


def test_trends_to_frame_columns():
    trends = compute_trends(_series("X", "m", [1, 2, 3]), metric_names=["m"])
    frame = trends_to_frame(trends)
    assert "slope_per_day" in frame.columns and "direction" in frame.columns


def test_anomaly_dod_jump():
    # Stable then a big jump on the last day.
    df = _series("X", "m", [100, 101, 100, 300])
    anomalies = detect_anomalies(df, factors=None, metric_names=["m"])
    jumps = [a for a in anomalies if a.method == "dod_jump"]
    assert any(a.date == "2026-01-04" for a in jumps)


def test_anomaly_zscore_flags_spike():
    df = _series("X", "m", [10, 10, 10, 10, 10, 10, 500])
    anomalies = detect_anomalies(df, factors=None, metric_names=["m"])
    zs = [a for a in anomalies if a.method == "zscore"]
    assert any(a.value == 500.0 for a in zs)


def test_anomaly_flat_series_none():
    df = _series("X", "m", [50, 50, 50, 50])
    anomalies = detect_anomalies(df, factors=None, metric_names=["m"])
    assert anomalies == []


def test_anomaly_short_series_skips_distribution():
    # Only 2 points: distribution detectors skipped (min_points=3 default), but
    # a big day-over-day jump still flags.
    df = _series("X", "m", [100, 200])
    anomalies = detect_anomalies(df, factors=None, metric_names=["m"])
    assert all(a.method == "dod_jump" for a in anomalies)
    assert len(anomalies) == 1


def test_anomaly_config_threshold_tuning():
    df = _series("X", "m", [100, 130])  # +30% jump
    # Default 40% threshold: no flag.
    assert detect_anomalies(df, factors=None, metric_names=["m"]) == []
    # Lower threshold via config: flagged.
    factors = {"analytics": {"anomaly": {"day_over_day_pct_jump": 0.2, "min_points": 3,
                                          "zscore_threshold": 2.0, "iqr_multiplier": 1.5}}}
    assert len(detect_anomalies(df, factors=factors, metric_names=["m"])) == 1


def test_on_generated_data(generated_output_dir, factors):
    result = load(generated_output_dir)
    m = compute_metrics(result.frame, factors)
    trends = compute_trends(m, factors=factors)
    # 3 entities x number of configured trend metrics present.
    assert len(trends) > 0
    assert {t.entity for t in trends} == {"Wells", "BoFA", "Chase"}
    anomalies = detect_anomalies(m, factors=factors)
    frame = anomalies_to_frame(anomalies)
    assert list(frame.columns) == ["entity", "date", "metric", "method", "value", "reason"]
