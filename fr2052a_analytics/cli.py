"""Command-line entry point for the FR 2052a liquidity surveillance engine.

Usage:
    analyze --input ./output --out ./analysis --format json

The command loads phase-1 output files, computes liquidity metrics, evaluates
the rule engine, runs trend / anomaly / peer / forecast analytics, and writes a
surveillance report. This module currently implements argument parsing and a
resolved-config summary; pipeline stages are wired in later tasks.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INPUT = "./output"
DEFAULT_OUT = "./analysis"
DEFAULT_CONFIG = "analytics_config"
VALID_FORMATS = ("json", "csv", "text")

# Exit codes (parallel to the generator's convention).
EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_CONFIG_ERROR = 3


class AnalyzeError(Exception):
    """Base error for the analytics pipeline (input/config/runtime)."""


class InputError(AnalyzeError):
    """Raised when the input data cannot be discovered or read."""


class ConfigError(AnalyzeError):
    """Raised when metric/rule configuration is missing or invalid."""


@dataclass
class Config:
    """Resolved, validated CLI configuration."""

    input_dir: Path
    out: Path
    fmt: str
    config_dir: Path
    banks: list[str] | None = None
    peers: list[str] | None = None
    forecast_days: int = 0
    _reserved: dict = field(default_factory=dict)


def _parse_csv_list(value: str) -> list[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected at least one comma-separated value")
    return items


def _non_negative_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got '{value}'")
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyze",
        description=(
            "Analyze FR 2052a mock submission files: liquidity metrics, rule-engine "
            "findings, trend/anomaly/peer analytics, and an experimental forecast. "
            "Operates on synthetic data only."
        ),
    )
    parser.add_argument(
        "--input", dest="input_dir", type=Path, default=Path(DEFAULT_INPUT),
        help=f"Directory of phase-1 output files (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--out", type=Path, default=Path(DEFAULT_OUT),
        help=f"Output directory for the report (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--format", dest="fmt", choices=VALID_FORMATS, default="json",
        help="Report output format (default: json)",
    )
    parser.add_argument(
        "--config", dest="config_dir", type=Path, default=Path(DEFAULT_CONFIG),
        help=f"Directory of metric/rule config files (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--banks", type=_parse_csv_list, default=None,
        help="Optional comma-separated subset of banks to analyze (default: all found)",
    )
    parser.add_argument(
        "--peers", type=_parse_csv_list, default=None,
        help="Optional comma-separated peer set for comparison (default: all found)",
    )
    parser.add_argument(
        "--forecast-days", dest="forecast_days", type=_non_negative_int, default=0,
        help="Experimental: number of days to project key metrics forward (default: 0 = off)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> Config:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return Config(
        input_dir=ns.input_dir,
        out=ns.out,
        fmt=ns.fmt,
        config_dir=ns.config_dir,
        banks=ns.banks,
        peers=ns.peers,
        forecast_days=ns.forecast_days,
    )


def _print_config_summary(config: Config) -> None:
    print("FR 2052a liquidity surveillance — resolved configuration:")
    print(f"  input dir     : {config.input_dir}")
    print(f"  output dir    : {config.out}")
    print(f"  report format : {config.fmt}")
    print(f"  config dir    : {config.config_dir}")
    print(f"  banks filter  : {', '.join(config.banks) if config.banks else '(all)'}")
    print(f"  peer set      : {', '.join(config.peers) if config.peers else '(all)'}")
    print(
        f"  forecast      : {'off' if config.forecast_days == 0 else str(config.forecast_days) + ' day(s) [experimental]'}"
    )


def run(config: Config) -> int:
    """Execute the full analytics pipeline and write the report.

    Runs loader -> metrics -> rules -> trend/anomaly/peer/forecast -> report,
    then prints a run summary. Import of the pipeline/report modules is local so
    that ``--help`` and arg parsing stay dependency-light.
    """
    from .pipeline import run_pipeline
    from .report import write_report

    _print_config_summary(config)

    result = run_pipeline(
        input_dir=config.input_dir,
        config_dir=config.config_dir,
        banks=config.banks,
        peers=config.peers,
        forecast_days=config.forecast_days,
    )

    print(
        f"Loaded {len(result.files)} file(s): "
        f"{len(result.entities)} entity(ies) x {len(result.dates)} day(s)."
    )
    sev = result.severity_summary()
    print(
        "Findings by severity: "
        + ", ".join(f"{lvl}={sev.get(lvl, 0)}" for lvl in
                    ("critical", "high", "medium", "low", "info"))
        + f" (total {len(result.findings)})."
    )
    print(
        f"Analytics: {len(result.trends)} trend series, "
        f"{len(result.anomalies)} anomaly flag(s), "
        f"{len(result.peers)} peer comparison(s)"
        + (f", {len(result.forecast)} forecast point(s) [experimental]" if result.forecast else "")
        + "."
    )

    written = write_report(result, config.out, config.fmt)
    for path in written:
        print(f"  wrote {path}")
    print(f"Done. Report written to '{config.out}' as {config.fmt}.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        return run(config)
    except InputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except AnalyzeError as exc:
        print(f"Analysis error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
