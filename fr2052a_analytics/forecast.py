"""Experimental short-horizon forecast of liquidity metrics.

EXPERIMENTAL: this is a deliberately simple projection (linear least-squares
trend or trailing moving average) intended to illustrate directional movement,
not a validated predictive model. On synthetic data it reflects the generator's
statistical shape rather than real market behavior. Every forecast record is
flagged ``experimental=True`` and callers should surface it as such.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .metrics import DATE, ENTITY
from .trend import DEFAULT_TREND_METRICS

DEFAULT_FORECAST = {"method": "linear", "moving_average_window": 3, "min_points": 3}


@dataclass
class ForecastPoint:
    """A single projected value for an (entity, metric, future date)."""

    entity: str
    metric: str
    date: str
    value: float
    method: str
    experimental: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _forecast_cfg(factors: dict | None) -> dict:
    cfg = dict(DEFAULT_FORECAST)
    if factors:
        cfg.update(factors.get("analytics", {}).get("forecast", {}) or {})
    return cfg


def _metric_names(factors: dict | None, metric_names: list[str] | None) -> list[str]:
    if metric_names:
        return metric_names
    if factors:
        cfg = factors.get("analytics", {}).get("trend_metrics")
        if cfg:
            return list(cfg)
    return DEFAULT_TREND_METRICS


def _project_linear(x: np.ndarray, y: np.ndarray, future_x: np.ndarray) -> np.ndarray:
    slope, intercept = np.polyfit(x, y, 1)
    return slope * future_x + intercept


def _project_moving_average(y: np.ndarray, window: int, horizon: int) -> np.ndarray:
    w = min(window, len(y))
    avg = float(np.mean(y[-w:]))
    return np.full(horizon, avg, dtype=float)


def forecast_metrics(metrics: pd.DataFrame, horizon_days: int,
                     factors: dict | None = None,
                     metric_names: list[str] | None = None) -> list[ForecastPoint]:
    """Project each (entity, metric) series ``horizon_days`` days forward.

    Series with fewer than ``min_points`` observations are skipped (guarded).
    Returns an empty list if ``horizon_days`` <= 0.
    """
    if horizon_days <= 0 or metrics.empty:
        return []
    cfg = _forecast_cfg(factors)
    method = str(cfg.get("method", "linear"))
    ma_window = int(cfg.get("moving_average_window", 3))
    min_points = int(cfg.get("min_points", 3))

    names = _metric_names(factors, metric_names)
    available = [m for m in names if m in metrics.columns]

    points: list[ForecastPoint] = []
    for entity, grp in metrics.sort_values(DATE).groupby(ENTITY, sort=True):
        dates = pd.to_datetime(grp[DATE])
        last_date = dates.max()
        future_dates = [last_date + pd.Timedelta(days=i) for i in range(1, horizon_days + 1)]
        for metric in available:
            series = pd.to_numeric(grp[metric], errors="coerce")
            mask = series.notna()
            y = series[mask].to_numpy(dtype=float)
            d = dates[mask]
            if len(y) < min_points:
                continue  # not enough history to project

            if method == "moving_average":
                projected = _project_moving_average(y, ma_window, horizon_days)
                used = "moving_average"
            else:
                day0 = d.min()
                x = (d - day0).dt.days.to_numpy(dtype=float)
                if np.ptp(x) == 0:
                    continue
                future_x = np.array([(fd - day0).days for fd in future_dates], dtype=float)
                projected = _project_linear(x, y, future_x)
                used = "linear"

            for fd, val in zip(future_dates, projected):
                points.append(ForecastPoint(
                    entity=str(entity),
                    metric=metric,
                    date=fd.strftime("%Y-%m-%d"),
                    value=float(val),
                    method=used,
                    experimental=True,
                ))

    points.sort(key=lambda p: (p.entity, p.metric, p.date))
    return points


def forecast_to_frame(points: list[ForecastPoint]) -> pd.DataFrame:
    """Return forecast points as a DataFrame (empty with columns if none)."""
    cols = ["entity", "metric", "date", "value", "method", "experimental"]
    if not points:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([p.to_dict() for p in points])[cols]
