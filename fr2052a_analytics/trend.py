"""Trend analysis over per-entity/day liquidity metrics.

Given the metrics frame from :func:`fr2052a_analytics.metrics.compute_metrics`,
this module summarizes how each metric moves over time for each entity: overall
slope (least-squares per day), first/last values, total and average
day-over-day change, and the latest day-over-day delta. Purely descriptive and
deterministic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .metrics import DATE, ENTITY

DEFAULT_TREND_METRICS = [
    "approx_lcr", "hqla_stock", "stress_outflows", "net_outflows",
    "stwf_reliance", "insured_deposit_share", "secured_rollover_share",
    "intercompany_trapped_share", "downgrade_drain_to_hqla",
]


@dataclass
class TrendSummary:
    """Trend summary for one (entity, metric) series."""

    entity: str
    metric: str
    n_points: int
    first_value: float
    last_value: float
    min_value: float
    max_value: float
    slope_per_day: float
    total_change: float
    avg_daily_change: float
    latest_delta: float
    direction: str  # "up" | "down" | "flat"

    def to_dict(self) -> dict:
        return asdict(self)


def _direction(slope: float, tol: float = 1e-9) -> str:
    if slope > tol:
        return "up"
    if slope < -tol:
        return "down"
    return "flat"


def _slope_per_day(dates: pd.Series, values: np.ndarray) -> float:
    """Least-squares slope of values vs. day offset. 0 if <2 points or flat x."""
    if len(values) < 2:
        return 0.0
    day0 = dates.min()
    x = (dates - day0).dt.days.to_numpy(dtype=float)
    if np.ptp(x) == 0:
        return 0.0
    # numpy polyfit degree 1 -> slope is coefficient[0].
    slope, _ = np.polyfit(x, values, 1)
    slope = float(slope)
    # Snap floating-point noise to zero so genuinely flat series read as flat.
    scale = max(abs(values.max()), abs(values.min()), 1.0)
    if abs(slope) < 1e-9 * scale:
        return 0.0
    return slope


def _trend_metrics(factors: dict | None) -> list[str]:
    if factors:
        cfg = factors.get("analytics", {}).get("trend_metrics")
        if cfg:
            return list(cfg)
    return DEFAULT_TREND_METRICS


def compute_trends(metrics: pd.DataFrame, factors: dict | None = None,
                   metric_names: list[str] | None = None) -> list[TrendSummary]:
    """Compute a trend summary per (entity, metric).

    Args:
        metrics: per-entity/day metrics frame.
        factors: optional factors config (supplies the metric list).
        metric_names: explicit metric list, overrides config/default.

    Returns:
        List of TrendSummary, sorted by entity then metric.
    """
    if metrics.empty:
        return []
    names = metric_names or _trend_metrics(factors)
    available = [m for m in names if m in metrics.columns]

    summaries: list[TrendSummary] = []
    for entity, grp in metrics.sort_values(DATE).groupby(ENTITY, sort=True):
        for metric in available:
            series = pd.to_numeric(grp[metric], errors="coerce")
            mask = series.notna()
            vals = series[mask].to_numpy(dtype=float)
            dates = grp.loc[mask, DATE]
            if len(vals) == 0:
                continue
            slope = _slope_per_day(dates, vals)
            deltas = np.diff(vals) if len(vals) > 1 else np.array([0.0])
            summaries.append(TrendSummary(
                entity=str(entity),
                metric=metric,
                n_points=int(len(vals)),
                first_value=float(vals[0]),
                last_value=float(vals[-1]),
                min_value=float(vals.min()),
                max_value=float(vals.max()),
                slope_per_day=slope,
                total_change=float(vals[-1] - vals[0]),
                avg_daily_change=float(deltas.mean()),
                latest_delta=float(deltas[-1]),
                direction=_direction(slope),
            ))
    summaries.sort(key=lambda s: (s.entity, s.metric))
    return summaries


def trends_to_frame(trends: list[TrendSummary]) -> pd.DataFrame:
    """Return trend summaries as a DataFrame (empty with columns if none)."""
    cols = ["entity", "metric", "n_points", "first_value", "last_value",
            "min_value", "max_value", "slope_per_day", "total_change",
            "avg_daily_change", "latest_delta", "direction"]
    if not trends:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([t.to_dict() for t in trends])[cols]
