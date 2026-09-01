"""Tests for the analytics CLI argument parsing and config summary."""
from __future__ import annotations

from pathlib import Path

import pytest

from fr2052a_analytics.cli import EXIT_INPUT_ERROR, EXIT_OK, main, parse_args


def test_parse_defaults():
    cfg = parse_args([])
    assert str(cfg.input_dir) == "output" or cfg.input_dir == Path("./output")
    assert cfg.fmt == "json"
    assert str(cfg.config_dir) == "analytics_config"
    assert cfg.banks is None
    assert cfg.peers is None
    assert cfg.forecast_days == 0


def test_parse_full():
    cfg = parse_args([
        "--input", "somedir",
        "--out", "outdir",
        "--format", "csv",
        "--config", "cfgdir",
        "--banks", "Wells,BoFA, Chase",
        "--peers", "Wells,Chase",
        "--forecast-days", "3",
    ])
    assert str(cfg.input_dir) == "somedir"
    assert str(cfg.out) == "outdir"
    assert cfg.fmt == "csv"
    assert str(cfg.config_dir) == "cfgdir"
    assert cfg.banks == ["Wells", "BoFA", "Chase"]
    assert cfg.peers == ["Wells", "Chase"]
    assert cfg.forecast_days == 3


def test_bad_format():
    with pytest.raises(SystemExit):
        parse_args(["--format", "xml"])


def test_empty_banks_list():
    with pytest.raises(SystemExit):
        parse_args(["--banks", " , "])


def test_negative_forecast_days():
    with pytest.raises(SystemExit):
        parse_args(["--forecast-days", "-1"])


def test_run_missing_input_dir_returns_error(tmp_path):
    missing = tmp_path / "does_not_exist"
    code = main(["--input", str(missing)])
    assert code == EXIT_INPUT_ERROR


def test_run_empty_input_dir_returns_error(tmp_path):
    """An input dir with no FR2052a files is an input error."""
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main(["--input", str(empty)])
    assert code == EXIT_INPUT_ERROR


def test_run_missing_config_returns_config_error(tmp_path):
    """Valid data but a missing config dir -> config error (exit 3)."""
    from fr2052a_analytics.cli import EXIT_CONFIG_ERROR

    d = tmp_path / "in"
    d.mkdir()
    (d / "FR2052a_Wells_20260101.csv").write_text(
        "Table,SubTable,ReportingEntity,ReportDate,Product,MarketValue\n"
        "Inflows,Assets,Wells,2026-01-01,I.A.1,100.0\n",
        encoding="utf-8",
    )
    code = main(["--input", str(d), "--config", str(tmp_path / "no_config"),
                 "--out", str(tmp_path / "out")])
    assert code == EXIT_CONFIG_ERROR
