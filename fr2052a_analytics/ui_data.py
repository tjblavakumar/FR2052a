"""Presentation-layer data preparation for the Streamlit UI.

These helpers shape an :class:`~fr2052a_analytics.pipeline.AnalysisResult` (and
its frames) into the small tables the dashboard renders. They contain NO
Streamlit imports so they are unit-testable without launching a UI;
``Dashboard.py`` imports and calls them.
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


def findings_grouped_by_rule(result: AnalysisResult, entity: str) -> list[dict]:
    """One summary dict per rule that fired for the entity, ordered by severity
    (critical first via SEVERITY_ORDER) then rule_id.

    Each summary contains rule metadata plus a breach-pattern summary:
    count, first_date, last_date, worst_value/worst_date (highest breach_ratio,
    ties broken by earliest date), latest_value/latest_date (max date), and the
    sorted list of breach dates. Returns ``[]`` when the entity has no findings.
    """
    frame = findings_for_entity(result, entity)
    if frame.empty:
        return []

    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    groups: list[dict] = []
    for rule_id, grp in frame.groupby("rule_id", sort=False):
        # Severity: use the most severe present to be safe.
        severity = min(
            grp["severity"].tolist(),
            key=lambda s: order.get(s, len(order)),
        )

        def _first_non_empty(col: str) -> str:
            for val in grp[col].tolist():
                if val not in (None, "") and not pd.isna(val):
                    return val
            return ""

        # Worst = highest breach_ratio; tie -> earliest date.
        worst = grp.sort_values(["breach_ratio", "date"], ascending=[False, True]).iloc[0]
        # Latest = max date.
        latest = grp.sort_values("date").iloc[-1]
        dates = sorted(grp["date"].tolist())

        groups.append({
            "rule_id": rule_id,
            "severity": severity,
            "metric": grp["metric"].iloc[0],
            "threshold": grp["threshold"].iloc[0],
            "op": grp["op"].iloc[0],
            "description": _first_non_empty("description"),
            "rationale": _first_non_empty("rationale"),
            "recommended_action": _first_non_empty("recommended_action"),
            "count": int(len(grp)),
            "first_date": min(dates),
            "last_date": max(dates),
            "worst_value": float(worst["value"]),
            "worst_date": worst["date"],
            "latest_value": float(latest["value"]),
            "latest_date": latest["date"],
            "dates": dates,
        })

    groups.sort(key=lambda g: (order.get(g["severity"], len(order)), g["rule_id"]))
    return groups


def rule_breach_table(result: AnalysisResult, entity: str, rule_id: str) -> pd.DataFrame:
    """Per-day breach rows for one rule/entity: columns [date, value, breach_pct]
    sorted by date. ``breach_pct = min(breach_ratio, 1) * 100`` rounded to 1
    decimal. Empty frame with those columns if none.
    """
    cols = ["date", "value", "breach_pct"]
    frame = findings_for_entity(result, entity)
    if frame.empty:
        return pd.DataFrame(columns=cols)
    sub = frame[frame["rule_id"] == rule_id].copy()
    if sub.empty:
        return pd.DataFrame(columns=cols)
    sub["breach_pct"] = sub["breach_ratio"].apply(
        lambda r: round(min(float(r), 1.0) * 100.0, 1)
    )
    out = sub[["date", "value", "breach_pct"]].sort_values("date")
    return out.reset_index(drop=True)


def breach_chart_data(result: AnalysisResult, entity: str, metric: str,
                      breach_dates, selected_date: str | None = None) -> pd.DataFrame:
    """Return the entity's metric actuals as columns [date, value, status] where
    status is 'breach' if date in ``breach_dates`` else 'ok'; plus a boolean
    'selected' column true only for ``selected_date``.

    Uses ``metric_with_forecast`` actuals only (series=='actual'). Empty frame
    with columns [date, value, status, selected] if no data.
    """
    cols = ["date", "value", "status", "selected"]
    df = metric_with_forecast(result, entity, metric)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df[df["series"] == "actual"].drop(columns=["series"]).copy()
    if df.empty:
        return pd.DataFrame(columns=cols)
    breach_set = set(breach_dates or [])
    df["status"] = df["date"].apply(lambda d: "breach" if d in breach_set else "ok")
    df["selected"] = df["date"].apply(lambda d: selected_date is not None and d == selected_date)
    return df[cols].reset_index(drop=True)
