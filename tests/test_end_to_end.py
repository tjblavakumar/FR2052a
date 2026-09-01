"""End-to-end test: 5 banks x 5 days => 25 files."""
from __future__ import annotations

import json

import pandas as pd

from fr2052a_mockgen.cli import parse_args, run

BANKS = ["Wells", "BoFA", "USWest", "Chase", "CapOne"]


def _run(tmp_path, fmt):
    cfg = parse_args([
        "--banks", ",".join(BANKS),
        "--start", "2022-01-01",
        "--days", "5",
        "--format", fmt,
        "--out", str(tmp_path),
        "--seed", "123",
    ])
    return run(cfg)


def test_csv_generates_25_files(tmp_path):
    written = _run(tmp_path, "csv")
    files = sorted(tmp_path.glob("*.csv"))
    assert len(written) == 25
    assert len(files) == 25
    # spot check names and content
    assert (tmp_path / "FR2052a_Wells_20220101.csv") in files
    assert (tmp_path / "FR2052a_CapOne_20220105.csv") in files
    for f in files:
        df = pd.read_csv(f)
        assert len(df) > 0
        assert list(df.columns)[:5] == [
            "Table", "SubTable", "ReportingEntity", "ReportDate", "Product",
        ]


def test_json_generates_25_files(tmp_path):
    written = _run(tmp_path, "json")
    files = sorted(tmp_path.glob("*.json"))
    assert len(written) == 25
    assert len(files) == 25
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        assert payload["report"] == "FR 2052a"
        assert payload["rowCount"] == len(payload["rows"])
        assert payload["rowCount"] > 0


def test_seed_reproducible(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for out in (a, b):
        cfg = parse_args([
            "--banks", "Wells",
            "--start", "2022-01-01",
            "--days", "1",
            "--format", "csv",
            "--out", str(out),
            "--seed", "999",
        ])
        run(cfg)
    fa = (a / "FR2052a_Wells_20220101.csv").read_text(encoding="utf-8")
    fb = (b / "FR2052a_Wells_20220101.csv").read_text(encoding="utf-8")
    assert fa == fb
