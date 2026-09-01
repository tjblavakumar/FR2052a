"""Tests for CLI argument parsing and validation."""
from __future__ import annotations

from datetime import date

import pytest

from fr2052a_mockgen.cli import parse_args


def test_parse_minimal():
    cfg = parse_args(["--banks", "Wells", "--start", "2022-01-01"])
    assert cfg.banks == ["Wells"]
    assert cfg.start == date(2022, 1, 1)
    assert cfg.days == 1
    assert cfg.fmt == "csv"


def test_parse_full():
    cfg = parse_args([
        "--banks", "Wells,BoFA, Chase",
        "--start", "2022-06-01",
        "--days", "5",
        "--format", "json",
        "--out", "outdir",
        "--seed", "7",
    ])
    assert cfg.banks == ["Wells", "BoFA", "Chase"]
    assert cfg.days == 5
    assert cfg.fmt == "json"
    assert cfg.seed == 7


def test_bad_date():
    with pytest.raises(SystemExit):
        parse_args(["--banks", "Wells", "--start", "01-01-2022"])


def test_bad_format():
    with pytest.raises(SystemExit):
        parse_args(["--banks", "Wells", "--start", "2022-01-01", "--format", "xml"])


def test_days_must_be_positive():
    with pytest.raises(SystemExit):
        parse_args(["--banks", "Wells", "--start", "2022-01-01", "--days", "0"])


def test_empty_banks():
    with pytest.raises(SystemExit):
        parse_args(["--banks", " , ", "--start", "2022-01-01"])


def test_banks_required():
    with pytest.raises(SystemExit):
        parse_args(["--start", "2022-01-01"])


def test_parse_profiles_default():
    cfg = parse_args(["--banks", "Wells", "--start", "2022-01-01"])
    assert str(cfg.profiles) == "bank_profiles"


def test_missing_profile_returns_error_code(tmp_path):
    from fr2052a_mockgen.cli import main
    empty = tmp_path / "empty_profiles"
    empty.mkdir()
    out = tmp_path / "out"
    code = main([
        "--banks", "NoSuchBank",
        "--start", "2022-01-01",
        "--out", str(out),
        "--profiles", str(empty),
    ])
    assert code == 3


def test_run_with_custom_profiles_dir(profiles_dir, tmp_path):
    from fr2052a_mockgen.cli import parse_args as pa, run
    out = tmp_path / "out"
    cfg = pa([
        "--banks", "TestBank",
        "--start", "2022-01-01",
        "--out", str(out),
        "--profiles", str(profiles_dir),
        "--seed", "1",
    ])
    written = run(cfg)
    assert len(written) == 1
    assert written[0].name == "FR2052a_TestBank_20220101.csv"
