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


def severity_color_scale(order: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Return (domain, range) for an Altair color scale keyed to SEVERITY_COLORS.

    ``domain`` is the severity labels in ``order`` (defaults to SEVERITY_ORDER);
    ``range`` is the matching hex colors. Single source of truth so the severity
    bar chart and the legend always use identical colors.
    """
    labels = order or SEVERITY_ORDER
    domain = [s for s in labels]
    range_ = [SEVERITY_COLORS.get(s, "#999999") for s in labels]
    return domain, range_


# Default plain-language severity definitions used when config does not supply
# a ``severity_definitions`` block (mirrors analytics_config/rules.json).
SEVERITY_DEFINITIONS_FALLBACK = {
    "critical": "Imminent liquidity threat: a core buffer or coverage measure has failed by a wide margin and warrants immediate escalation.",
    "high": "Serious concern: a regulatory or structural threshold is breached; investigate promptly and monitor daily.",
    "medium": "Elevated risk: a funding-shape or concentration indicator is outside its comfort band; review and track the trend.",
    "low": "Watch item: a soft threshold or cross-check flag; note it and confirm it does not worsen.",
    "info": "Informational: surfaced for awareness, no action implied.",
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


def finding_detail(result: AnalysisResult, index: int) -> dict:
    """Return the ``to_dict()`` of one finding by position, or ``{}`` if out of range."""
    findings = result.findings
    if index < 0 or index >= len(findings):
        return {}
    return findings[index].to_dict()


def _get(obj, key, default=None):
    """Read ``key`` from a Finding-like object (attribute) or a dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def gauge_data(finding) -> dict:
    """Shape a finding (object or dict) into gauge-ready fields for the UI.

    ``percent`` is ``min(breach_ratio, 1.0) * 100`` clamped to [0, 100], suitable
    for a 0-100 breach-magnitude display.
    """
    severity = _get(finding, "severity", "info")
    try:
        breach_ratio = float(_get(finding, "breach_ratio", 0.0) or 0.0)
    except (TypeError, ValueError):
        breach_ratio = 0.0
    try:
        value = float(_get(finding, "value", 0.0) or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    percent = min(max(breach_ratio, 0.0), 1.0) * 100.0
    percent = min(max(percent, 0.0), 100.0)
    return {
        "value": value,
        "threshold": _get(finding, "threshold"),
        "breach_ratio": breach_ratio,
        "severity": severity,
        "color": SEVERITY_COLORS.get(severity, "#999999"),
        "percent": percent,
    }


def severity_definitions(defs: dict | None = None) -> dict:
    """Return ``defs`` if it is truthy, otherwise the built-in fallback definitions."""
    return defs if defs else SEVERITY_DEFINITIONS_FALLBACK


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
