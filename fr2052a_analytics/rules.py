"""Declarative rule engine for FR 2052a liquidity metrics.

Rules are loaded from ``analytics_config/rules.json`` and evaluated against the
per-entity/day metrics frame produced by
:func:`fr2052a_analytics.metrics.compute_metrics`. Each rule compares a metric
column against a threshold with a comparison operator; a satisfied rule emits a
structured :class:`Finding`.

Keeping rules in config lets analysts add, retune, or disable checks without
touching code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .cli import ConfigError
from .metrics import DATE, ENTITY

VALID_SEVERITIES = ("info", "low", "medium", "high", "critical")
_SEVERITY_ORDER = {s: i for i, s in enumerate(VALID_SEVERITIES)}

# Scalar comparison operators.
_SCALAR_OPS = {
    "lt": lambda v, t: v < t,
    "le": lambda v, t: v <= t,
    "gt": lambda v, t: v > t,
    "ge": lambda v, t: v >= t,
    "eq": lambda v, t: v == t,
    "ne": lambda v, t: v != t,
}
# Range operators expect threshold = [low, high].
_RANGE_OPS = ("between", "outside")


@dataclass
class Finding:
    """A single rule breach for one entity/date."""

    entity: str
    date: str
    rule_id: str
    severity: str
    metric: str
    value: float
    threshold: object
    message: str
    description: str = ""
    rationale: str = ""
    recommended_action: str = ""
    breach_ratio: float = 0.0
    op: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_breach_ratio(op: str, value: float, threshold) -> float:
    """Return a non-negative, normalized magnitude of how far past the threshold ``value`` is.

    For scalar ops the result is the fractional distance past the threshold line
    (``abs(value - t) / abs(t)``, or ``abs(value - t)`` when ``t == 0``). For
    ``outside`` it measures how far beyond the nearer bound the value sits; a
    ``between`` breach (being inside the band) has magnitude 0. Any error yields
    ``0.0`` so metadata never breaks evaluation.
    """
    try:
        if op in _SCALAR_OPS:
            t = float(threshold)
            if t != 0:
                return abs(value - t) / abs(t)
            return abs(value - t)
        if op == "outside":
            low, high = float(threshold[0]), float(threshold[1])
            if value < low:
                return (abs(low - value) / abs(low)) if low != 0 else abs(low - value)
            if value > high:
                return (abs(value - high) / abs(high)) if high != 0 else abs(value - high)
            return 0.0
        if op == "between":
            return 0.0
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return 0.0
    return 0.0


def _validate_rule(rule: dict) -> None:
    for key in ("id", "metric", "op"):
        if key not in rule:
            raise ConfigError(f"Rule missing required key '{key}': {rule}")
    op = rule["op"]
    if op not in _SCALAR_OPS and op not in _RANGE_OPS:
        raise ConfigError(f"Rule '{rule['id']}' has unknown op '{op}'.")
    sev = rule.get("severity", "info")
    if sev not in VALID_SEVERITIES:
        raise ConfigError(
            f"Rule '{rule['id']}' has invalid severity '{sev}' "
            f"(expected one of {VALID_SEVERITIES})."
        )
    threshold = rule.get("threshold")
    if op in _RANGE_OPS:
        if not (isinstance(threshold, (list, tuple)) and len(threshold) == 2):
            raise ConfigError(
                f"Rule '{rule['id']}' op '{op}' requires a [low, high] threshold."
            )
    else:
        if not isinstance(threshold, (int, float)):
            raise ConfigError(
                f"Rule '{rule['id']}' op '{op}' requires a numeric threshold."
            )


def _op_holds(op: str, value: float, threshold) -> bool:
    if op in _SCALAR_OPS:
        return bool(_SCALAR_OPS[op](value, float(threshold)))
    low, high = float(threshold[0]), float(threshold[1])
    if op == "between":
        return low <= value <= high
    # outside
    return value < low or value > high


def _format_message(rule: dict, entity: str, date: str, value: float) -> str:
    template = rule.get("message", "{metric} = {value}")
    try:
        return template.format(
            metric=rule["metric"], value=value, threshold=rule.get("threshold"),
            entity=entity, date=date,
        )
    except (KeyError, ValueError, IndexError):
        # Fall back to a safe rendering if the template references unknowns.
        return f"{rule['metric']} = {value} ({rule['id']})"


def evaluate_rules(metrics: pd.DataFrame, rules: list[dict]) -> list[Finding]:
    """Evaluate ``rules`` against a metrics frame and return findings.

    Rows where the metric value is missing (NaN) are skipped for that rule.
    Findings are sorted by severity (most severe first), then entity, then date.
    """
    findings: list[Finding] = []
    for rule in rules:
        if rule.get("enabled", True) is False:
            continue
        _validate_rule(rule)
        metric = rule["metric"]
        if metric not in metrics.columns:
            # A rule referencing an absent metric is skipped (not an error) so
            # config can outlive schema changes; surfaced by callers if needed.
            continue
        op = rule["op"]
        threshold = rule.get("threshold")
        severity = rule.get("severity", "info")

        col = pd.to_numeric(metrics[metric], errors="coerce")
        for idx, value in col.items():
            if pd.isna(value):
                continue
            if _op_holds(op, float(value), threshold):
                entity = str(metrics.at[idx, ENTITY])
                date_val = metrics.at[idx, DATE]
                date = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)
                findings.append(Finding(
                    entity=entity,
                    date=date,
                    rule_id=rule["id"],
                    severity=severity,
                    metric=metric,
                    value=float(value),
                    threshold=threshold,
                    message=_format_message(rule, entity, date, float(value)),
                    description=rule.get("description", ""),
                    rationale=rule.get("rationale", ""),
                    recommended_action=rule.get("recommended_action", ""),
                    op=op,
                    breach_ratio=compute_breach_ratio(op, float(value), threshold),
                ))

    findings.sort(key=lambda f: (-_SEVERITY_ORDER.get(f.severity, 0), f.entity, f.date, f.rule_id))
    return findings


def findings_to_frame(findings: list[Finding]) -> pd.DataFrame:
    """Return findings as a DataFrame (empty with correct columns if none)."""
    cols = ["entity", "date", "rule_id", "severity", "metric", "value", "threshold", "message",
            "description", "rationale", "recommended_action", "breach_ratio", "op"]
    if not findings:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([f.to_dict() for f in findings]).reindex(columns=cols)


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    """Return a count of findings per severity level (all levels present)."""
    counts = {s: 0 for s in VALID_SEVERITIES}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
