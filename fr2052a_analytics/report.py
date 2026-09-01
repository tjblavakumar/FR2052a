"""Serialize an :class:`~fr2052a_analytics.pipeline.AnalysisResult` to disk.

Three output formats:
    * ``json`` -- a single ``analysis_report.json`` with all sections.
    * ``csv``  -- one CSV per section (metrics, findings, trends, anomalies,
                  peers, forecast, business_lines) in the output directory.
    * ``text`` -- a human-readable ``analysis_report.txt`` summary.

The JSON report is the canonical artifact the UI can also reload.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .anomaly import anomalies_to_frame
from .forecast import forecast_to_frame
from .peer import peers_to_frame
from .pipeline import AnalysisResult
from .rules import findings_to_frame
from .trend import trends_to_frame

REPORT_STEM = "analysis_report"
DISCLAIMER = (
    "Synthetic data only. Metrics are documented approximations of Regulation WW "
    "(LCR/NSFR) applied to FR 2052a fields, not exact regulatory calculations. "
    "Forecasts are experimental. See ANALYTICS_NOTES.md."
)


def _jsonable(value):
    """Convert numpy/pandas scalars to plain JSON-serializable values."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):  # numpy scalar
        try:
            return value.item()
        except (ValueError, TypeError):
            return value
    return value


def _frame_records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of JSON-safe row dicts."""
    if frame.empty:
        return []
    safe = frame.copy()
    # Normalize datetimes to strings.
    for col in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[col]):
            safe[col] = safe[col].dt.strftime("%Y-%m-%d")
    records = safe.to_dict(orient="records")
    return [{k: _jsonable(v) for k, v in rec.items()} for rec in records]


def build_report_dict(result: AnalysisResult) -> dict:
    """Assemble the full report as a nested, JSON-serializable dict."""
    return {
        "report": "FR 2052a Liquidity Surveillance",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "disclaimer": DISCLAIMER,
        "inputDir": str(result.input_dir),
        "fileCount": len(result.files),
        "entities": result.entities,
        "dates": result.dates,
        "severitySummary": result.severity_summary(),
        "metrics": _frame_records(result.metrics),
        "businessLines": _frame_records(result.business_lines),
        "findings": [f.to_dict() for f in result.findings],
        "trends": [t.to_dict() for t in result.trends],
        "anomalies": [a.to_dict() for a in result.anomalies],
        "peers": [p.to_dict() for p in result.peers],
        "forecast": [fp.to_dict() for fp in result.forecast],
    }


def write_json(result: AnalysisResult, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{REPORT_STEM}.json"
    path.write_text(json.dumps(build_report_dict(result), indent=2), encoding="utf-8")
    return path


def write_csv(result: AnalysisResult, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sections = {
        "metrics": result.metrics,
        "business_lines": result.business_lines,
        "findings": findings_to_frame(result.findings),
        "trends": trends_to_frame(result.trends),
        "anomalies": anomalies_to_frame(result.anomalies),
        "peers": peers_to_frame(result.peers),
        "forecast": forecast_to_frame(result.forecast),
    }
    written: list[Path] = []
    for name, frame in sections.items():
        path = out_dir / f"{REPORT_STEM}_{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)
    return written


def _format_text(result: AnalysisResult) -> str:
    lines: list[str] = []
    lines.append("FR 2052a Liquidity Surveillance Report")
    lines.append("=" * 44)
    lines.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Input dir : {result.input_dir}")
    lines.append(f"Files     : {len(result.files)}")
    lines.append(f"Entities  : {', '.join(result.entities)}")
    if result.dates:
        lines.append(f"Dates     : {result.dates[0]} .. {result.dates[-1]} ({len(result.dates)} day(s))")
    lines.append("")
    lines.append(f"DISCLAIMER: {DISCLAIMER}")
    lines.append("")

    sev = result.severity_summary()
    lines.append("Findings by severity:")
    for level in ("critical", "high", "medium", "low", "info"):
        lines.append(f"  {level:<9}: {sev.get(level, 0)}")
    lines.append("")

    # Top findings (most severe first; already sorted by evaluate_rules).
    lines.append("Top findings:")
    if not result.findings:
        lines.append("  (none)")
    for f in result.findings[:20]:
        lines.append(f"  [{f.severity.upper():<8}] {f.entity} {f.date} {f.rule_id}: {f.message}")
    if len(result.findings) > 20:
        lines.append(f"  ... and {len(result.findings) - 20} more")
    lines.append("")

    # Anomalies summary.
    lines.append(f"Anomalies detected: {len(result.anomalies)}")
    for a in result.anomalies[:10]:
        lines.append(f"  {a.entity} {a.date} {a.metric} [{a.method}]: {a.reason}")
    if len(result.anomalies) > 10:
        lines.append(f"  ... and {len(result.anomalies) - 10} more")
    lines.append("")

    if result.forecast:
        lines.append(f"Forecast (EXPERIMENTAL): {len(result.forecast)} projected point(s)")
    lines.append("")
    return "\n".join(lines)


def write_text(result: AnalysisResult, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{REPORT_STEM}.txt"
    path.write_text(_format_text(result), encoding="utf-8")
    return path


def write_report(result: AnalysisResult, out_dir: Path, fmt: str) -> list[Path]:
    """Write the report in ``fmt`` (json|csv|text). Returns written paths."""
    if fmt == "json":
        return [write_json(result, out_dir)]
    if fmt == "csv":
        return write_csv(result, out_dir)
    if fmt == "text":
        return [write_text(result, out_dir)]
    raise ValueError(f"Unsupported report format '{fmt}'")
