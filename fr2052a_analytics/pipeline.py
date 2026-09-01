"""End-to-end analytics pipeline orchestration.

Runs the full surveillance pipeline on an input directory:

    load -> compute_metrics + business-line breakdown
         -> rule findings
         -> trend / anomaly / peer / (optional) forecast

Returns an :class:`AnalysisResult` bundle consumed by both the CLI report
writer and the Streamlit UI, so the two share one code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import anomaly as anomaly_mod
from . import forecast as forecast_mod
from . import peer as peer_mod
from . import trend as trend_mod
from .config import load_factors, load_rules
from .loader import load
from .metrics import compute_business_line_breakdown, compute_metrics
from .rules import evaluate_rules, severity_counts


@dataclass
class AnalysisResult:
    """Bundle of everything the pipeline produced."""

    input_dir: Path
    files: list[Path]
    entities: list[str]
    dates: list[str]
    metrics: pd.DataFrame
    business_lines: pd.DataFrame
    findings: list
    trends: list
    anomalies: list
    peers: list
    forecast: list = field(default_factory=list)

    def severity_summary(self) -> dict:
        return severity_counts(self.findings)


def run_pipeline(input_dir: Path, config_dir: Path, banks: list[str] | None = None,
                 peers: list[str] | None = None, forecast_days: int = 0) -> AnalysisResult:
    """Execute the full pipeline and return an :class:`AnalysisResult`.

    Raises:
        InputError: from the loader if input is missing/empty.
        ConfigError: from config loading if factors/rules are invalid.
    """
    factors = load_factors(config_dir)
    rules = load_rules(config_dir)

    loaded = load(input_dir, banks=banks)
    frame = loaded.frame

    metrics = compute_metrics(frame, factors)
    business_lines = compute_business_line_breakdown(frame, factors)

    findings = evaluate_rules(metrics, rules)
    trends = trend_mod.compute_trends(metrics, factors=factors)
    anomalies = anomaly_mod.detect_anomalies(metrics, factors=factors)
    peer_comparisons = peer_mod.compare_peers(metrics, peers=peers, factors=factors)
    forecast_points = (
        forecast_mod.forecast_metrics(metrics, forecast_days, factors=factors)
        if forecast_days > 0 else []
    )

    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
             for d in loaded.dates]

    return AnalysisResult(
        input_dir=Path(input_dir),
        files=loaded.files,
        entities=loaded.entities,
        dates=dates,
        metrics=metrics,
        business_lines=business_lines,
        findings=findings,
        trends=trends,
        anomalies=anomalies,
        peers=peer_comparisons,
        forecast=forecast_points,
    )
