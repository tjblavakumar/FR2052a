"""Presentation-layer data preparation for the Streamlit UI.

These helpers shape an :class:`~fr2052a_analytics.pipeline.AnalysisResult` (and
its frames) into the small tables the dashboard renders. They contain NO
Streamlit imports so they are unit-testable without launching a UI; ``app.py``
imports and calls them.
"""
from __future__ import annotations

import pandas as pd

from .anomaly import anomalies_to_frame
from .forecast import forecast_to_frame
from .metrics import DATE, ENTITY
from .peer import peers_to_frame
from .pipeline import AnalysisResult
from .rules import findings_to_frame

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
SEVERITY_COLORS = {
    "critical": "#8B0000",
    "high": "#D9534F",
    "medium": "#F0AD4E",
    "low": "#5BC0DE",
    "info": "#999999",
}


def metric_timeseries(metrics: pd.DataFrame, entity: str, metric: str) -> pd.DataFrame:
    """Return a two-column (ReportDate, value) frame for one entity/metric.

    Empty frame (with columns) if the entity or metric is absent.
    """
    cols = [DATE, metric]
    if metric not in metrics.columns or ENTITY not in metrics.columns:
        return pd.DataFrame(columns=[DATE, "value"])
    sub = metrics[metrics[ENTITY] == entity][cols].copy()
    sub = sub.dropna(subset=[metric]).sort_values(DATE)
    sub = sub.rename(columns={metric: "value"})
    return sub.reset_index(drop=True)


def metric_with_forecast(result: AnalysisResult, entity: str, metric: str) -> pd.DataFrame:
    """Combine actual and (experimental) forecast series for charting.

    Returns columns [date, value, series] where ``series`` is 'actual' or
    'forecast (experimental)'.
    """
    actual = metric_timeseries(result.metrics, entity, metric)
    actual = actual.rename(columns={DATE: "date"})
    actual["series"] = "actual"

    fc = forecast_to_frame(result.forecast)
    if not fc.empty:
        fc = fc[(fc["entity"] == entity) & (fc["metric"] == metric)][["date", "value"]].copy()
        fc["series"] = "forecast (experimental)"
    else:
        fc = pd.DataFrame(columns=["date", "value", "series"])

    combined = pd.concat([actual[["date", "value", "series"]], fc], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
    return combined


def findings_for_entity(result: AnalysisResult, entity: str | None = None) -> pd.DataFrame:
    """Findings as a frame, optionally filtered to one entity, severity-sorted."""
    frame = findings_to_frame(result.findings)
    if frame.empty:
        return frame
    if entity is not None:
        frame = frame[frame["entity"] == entity]
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    frame = frame.assign(_o=frame["severity"].map(lambda s: order.get(s, len(order))))
    return frame.sort_values(["_o", "date", "rule_id"]).drop(columns="_o").reset_index(drop=True)


def anomalies_for_entity(result: AnalysisResult, entity: str | None = None) -> pd.DataFrame:
    frame = anomalies_to_frame(result.anomalies)
    if not frame.empty and entity is not None:
        frame = frame[frame["entity"] == entity].reset_index(drop=True)
    return frame


def peers_for_metric(result: AnalysisResult, metric: str) -> pd.DataFrame:
    """Peer comparison rows for one metric (all entities), sorted by rank."""
    frame = peers_to_frame(result.peers)
    if frame.empty:
        return frame
    frame = frame[frame["metric"] == metric]
    return frame.sort_values("percentile_rank", ascending=False).reset_index(drop=True)


def business_line_snapshot(result: AnalysisResult, entity: str, on_date: str | None = None) -> pd.DataFrame:
    """Business-line HQLA/outflows for one entity on a date (latest if None)."""
    bl = result.business_lines
    if bl.empty:
        return bl
    sub = bl[bl[ENTITY] == entity].copy()
    if sub.empty:
        return sub
    dates = pd.to_datetime(sub[DATE])
    target = pd.to_datetime(on_date) if on_date else dates.max()
    sub = sub[dates == target]
    return sub.reset_index(drop=True)


def severity_summary_frame(result: AnalysisResult) -> pd.DataFrame:
    """Severity counts as a two-column frame in fixed severity order."""
    counts = result.severity_summary()
    return pd.DataFrame(
        {"severity": SEVERITY_ORDER,
         "count": [counts.get(s, 0) for s in SEVERITY_ORDER]}
    )


def available_metrics(result: AnalysisResult) -> list[str]:
    """Numeric metric columns available for charting (excludes id columns)."""
    exclude = {ENTITY, DATE}
    cols = []
    for c in result.metrics.columns:
        if c in exclude:
            continue
        if pd.api.types.is_numeric_dtype(result.metrics[c]):
            cols.append(c)
    return cols
