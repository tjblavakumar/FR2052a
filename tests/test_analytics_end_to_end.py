"""End-to-end test: generate phase-1 data, run analyze, verify the report."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fr2052a_analytics.cli import EXIT_OK, main
from fr2052a_analytics.pipeline import run_pipeline
from fr2052a_analytics.report import build_report_dict, write_report

CONFIG_DIR = Path(__file__).resolve().parents[1] / "analytics_config"


def test_pipeline_bundle(generated_output_dir):
    result = run_pipeline(generated_output_dir, CONFIG_DIR, forecast_days=2)
    assert set(result.entities) == {"Wells", "BoFA", "Chase"}
    assert len(result.dates) == 6
    assert not result.metrics.empty
    assert len(result.findings) > 0
    assert len(result.trends) > 0
    assert len(result.forecast) > 0  # 2-day horizon, 6 days of history


def test_report_json_roundtrip(generated_output_dir):
    result = run_pipeline(generated_output_dir, CONFIG_DIR, forecast_days=1)
    d = build_report_dict(result)
    # JSON must be serializable (no NaN/numpy leaking through).
    text = json.dumps(d)
    reloaded = json.loads(text)
    assert reloaded["report"] == "FR 2052a Liquidity Surveillance"
    assert "disclaimer" in reloaded
    assert set(reloaded["entities"]) == {"Wells", "BoFA", "Chase"}
    assert reloaded["severitySummary"]["high"] >= 0


def test_cli_json_output(generated_output_dir, tmp_path):
    out = tmp_path / "analysis"
    code = main(["--input", str(generated_output_dir), "--config", str(CONFIG_DIR),
                 "--out", str(out), "--format", "json", "--forecast-days", "2"])
    assert code == EXIT_OK
    report = out / "analysis_report.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["fileCount"] == 18
    assert len(payload["forecast"]) > 0


def test_cli_csv_output(generated_output_dir, tmp_path):
    out = tmp_path / "analysis_csv"
    code = main(["--input", str(generated_output_dir), "--config", str(CONFIG_DIR),
                 "--out", str(out), "--format", "csv"])
    assert code == EXIT_OK
    for name in ("metrics", "findings", "trends", "anomalies", "peers",
                 "forecast", "business_lines"):
        path = out / f"analysis_report_{name}.csv"
        assert path.exists(), f"missing {path.name}"
    # Metrics CSV should be non-empty and readable.
    metrics = pd.read_csv(out / "analysis_report_metrics.csv")
    assert len(metrics) == 18


def test_cli_text_output(generated_output_dir, tmp_path):
    out = tmp_path / "analysis_text"
    code = main(["--input", str(generated_output_dir), "--config", str(CONFIG_DIR),
                 "--out", str(out), "--format", "text"])
    assert code == EXIT_OK
    report = out / "analysis_report.txt"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "FR 2052a Liquidity Surveillance Report" in content
    assert "Findings by severity" in content
    assert "DISCLAIMER" in content


def test_write_report_returns_paths(generated_output_dir, tmp_path):
    result = run_pipeline(generated_output_dir, CONFIG_DIR)
    paths = write_report(result, tmp_path / "r", "json")
    assert len(paths) == 1 and paths[0].exists()
