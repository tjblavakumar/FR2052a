"""Cross-institution (peer) comparison of liquidity metrics.

For a chosen reporting date, compares each entity's metric values against the
peer group: peer median and quartiles, and the entity's percentile rank within
the group. This supports benchmarking a firm's liquidity profile against
similar institutions, as in supervisory peer surveillance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .metrics import DATE, ENTITY
from .trend import DEFAULT_TREND_METRICS


@dataclass
class PeerComparison:
    """One entity's standing vs peers for one metric on one date."""

    entity: str
    date: str
    metric: str
    value: float
    peer_count: int
    peer_median: float
    peer_q1: float
    peer_q3: float
    percentile_rank: float  # 0..100, entity's rank within the peer group

    def to_dict(self) -> dict:
        return asdict(self)


def _metric_names(factors: dict | None, metric_names: list[str] | None) -> list[str]:
    if metric_names:
        return metric_names
    if factors:
        cfg = factors.get("analytics", {}).get("trend_metrics")
        if cfg:
            return list(cfg)
    return DEFAULT_TREND_METRICS


def _percentile_rank(value: float, population: np.ndarray) -> float:
    """Percentage of the population at or below ``value`` (0..100)."""
    if population.size == 0:
        return float("nan")
    return 100.0 * float(np.mean(population <= value))


def _resolve_date(metrics: pd.DataFrame, on_date) -> pd.Timestamp | None:
    dates = pd.to_datetime(metrics[DATE]).dropna()
    if dates.empty:
        return None
    if on_date is None:
        return dates.max()  # latest available date
    ts = pd.to_datetime(on_date)
    return ts if (dates == ts).any() else None


def compare_peers(metrics: pd.DataFrame, on_date=None, peers: list[str] | None = None,
                  factors: dict | None = None,
                  metric_names: list[str] | None = None) -> list[PeerComparison]:
    """Compare entities against peers for a given date.

    Args:
        metrics: per-entity/day metrics frame.
        on_date: date to compare on (default: latest date present).
        peers: optional subset defining the peer group (default: all entities
            present on that date).
        factors: optional factors config (supplies metric list).
        metric_names: explicit metric list, overrides config/default.

    Returns:
        List of PeerComparison, sorted by metric then entity. Empty if the date
        is not present or fewer than two peers exist.
    """
    if metrics.empty:
        return []
    target = _resolve_date(metrics, on_date)
    if target is None:
        return []

    day = metrics[pd.to_datetime(metrics[DATE]) == target].copy()
    if peers:
        peer_set = set(peers)
        day = day[day[ENTITY].isin(peer_set)]
    if day[ENTITY].nunique() < 2:
        return []

    names = _metric_names(factors, metric_names)
    available = [m for m in names if m in day.columns]
    date_str = target.strftime("%Y-%m-%d")

    results: list[PeerComparison] = []
    for metric in available:
        col = pd.to_numeric(day[metric], errors="coerce")
        valid = day.loc[col.notna(), [ENTITY]].copy()
        valid[metric] = col[col.notna()].to_numpy()
        population = valid[metric].to_numpy(dtype=float)
        if population.size < 2:
            continue
        median = float(np.median(population))
        q1, q3 = (float(x) for x in np.percentile(population, [25, 75]))
        for _, row in valid.iterrows():
            value = float(row[metric])
            results.append(PeerComparison(
                entity=str(row[ENTITY]),
                date=date_str,
                metric=metric,
                value=value,
                peer_count=int(population.size),
                peer_median=median,
                peer_q1=q1,
                peer_q3=q3,
                percentile_rank=_percentile_rank(value, population),
            ))

    results.sort(key=lambda r: (r.metric, r.entity))
    return results


def peers_to_frame(comparisons: list[PeerComparison]) -> pd.DataFrame:
    """Return peer comparisons as a DataFrame (empty with columns if none)."""
    cols = ["entity", "date", "metric", "value", "peer_count", "peer_median",
            "peer_q1", "peer_q3", "percentile_rank"]
    if not comparisons:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([c.to_dict() for c in comparisons])[cols]
