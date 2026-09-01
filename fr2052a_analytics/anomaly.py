"""Statistical anomaly detection over per-entity/day liquidity metrics.

All detectors are explainable and statistical (no ML), which suits a
supervisory context where every flag must be justifiable:

    * ``zscore``       -- point deviates > z-threshold std devs from the
                          entity's mean for that metric.
    * ``iqr``          -- point falls outside [Q1 - k*IQR, Q3 + k*IQR].
    * ``dod_jump``     -- day-over-day change exceeds a percentage threshold.

Each detector runs per (entity, metric) time series and yields an
:class:`Anomaly` with the reason and the numbers behind the flag. Thresholds
come from ``factors['analytics']['anomaly']`` so they are tunable via config.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .metrics import DATE, ENTITY
from .trend import DEFAULT_TREND_METRICS

DEFAULT_ANOMALY = {
    "zscore_threshold": 2.0,
    "iqr_multiplier": 1.5,
    "day_over_day_pct_jump": 0.40,
    "min_points": 3,
}


@dataclass
class Anomaly:
    """A single anomalous observation."""

    entity: str
    date: str
    metric: str
    method: str          # "zscore" | "iqr" | "dod_jump"
    value: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _anomaly_cfg(factors: dict | None) -> dict:
    cfg = dict(DEFAULT_ANOMALY)
    if factors:
        cfg.update(factors.get("analytics", {}).get("anomaly", {}) or {})
    return cfg


def _metric_names(factors: dict | None, metric_names: list[str] | None) -> list[str]:
    if metric_names:
        return metric_names
    if factors:
        cfg = factors.get("analytics", {}).get("trend_metrics")
        if cfg:
            return list(cfg)
    return DEFAULT_TREND_METRICS


def _date_str(value) -> str:
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)


def detect_anomalies(metrics: pd.DataFrame, factors: dict | None = None,
                     metric_names: list[str] | None = None) -> list[Anomaly]:
    """Detect statistical anomalies per (entity, metric) series.

    Series shorter than ``min_points`` are skipped for the distribution-based
    detectors (z-score, IQR); the day-over-day detector needs only 2 points.
    """
    if metrics.empty:
        return []
    cfg = _anomaly_cfg(factors)
    z_thresh = float(cfg["zscore_threshold"])
    iqr_mult = float(cfg["iqr_multiplier"])
    dod_thresh = float(cfg["day_over_day_pct_jump"])
    min_points = int(cfg["min_points"])

    names = _metric_names(factors, metric_names)
    available = [m for m in names if m in metrics.columns]

    anomalies: list[Anomaly] = []
    for entity, grp in metrics.sort_values(DATE).groupby(ENTITY, sort=True):
        grp = grp.reset_index(drop=True)
        for metric in available:
            series = pd.to_numeric(grp[metric], errors="coerce")
            mask = series.notna()
            vals = series[mask].to_numpy(dtype=float)
            dates = grp.loc[mask, DATE].tolist()
            if len(vals) == 0:
                continue

            # Distribution-based detectors need enough points.
            if len(vals) >= min_points:
                mean = float(vals.mean())
                std = float(vals.std(ddof=0))
                if std > 0:
                    for v, d in zip(vals, dates):
                        z = (v - mean) / std
                        if abs(z) > z_thresh:
                            anomalies.append(Anomaly(
                                entity=str(entity), date=_date_str(d), metric=metric,
                                method="zscore", value=float(v),
                                reason=f"z-score {z:.2f} exceeds +/-{z_thresh} (mean {mean:.3g}, std {std:.3g})",
                            ))

                q1, q3 = np.percentile(vals, [25, 75])
                iqr = q3 - q1
                if iqr > 0:
                    lo, hi = q1 - iqr_mult * iqr, q3 + iqr_mult * iqr
                    for v, d in zip(vals, dates):
                        if v < lo or v > hi:
                            anomalies.append(Anomaly(
                                entity=str(entity), date=_date_str(d), metric=metric,
                                method="iqr", value=float(v),
                                reason=f"outside IQR fence [{lo:.3g}, {hi:.3g}] (k={iqr_mult})",
                            ))

            # Day-over-day jump needs only two consecutive points.
            for i in range(1, len(vals)):
                prev, cur = vals[i - 1], vals[i]
                if prev == 0:
                    continue
                pct = (cur - prev) / abs(prev)
                if abs(pct) > dod_thresh:
                    anomalies.append(Anomaly(
                        entity=str(entity), date=_date_str(dates[i]), metric=metric,
                        method="dod_jump", value=float(cur),
                        reason=f"day-over-day change {pct:+.0%} exceeds +/-{dod_thresh:.0%} (prev {prev:.3g})",
                    ))

    anomalies.sort(key=lambda a: (a.entity, a.metric, a.date, a.method))
    return anomalies


def anomalies_to_frame(anomalies: list[Anomaly]) -> pd.DataFrame:
    """Return anomalies as a DataFrame (empty with columns if none)."""
    cols = ["entity", "date", "metric", "method", "value", "reason"]
    if not anomalies:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([a.to_dict() for a in anomalies])[cols]
