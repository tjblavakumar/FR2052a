"""Command-line entry point for the FR 2052a mock data generator.

Usage:
    generate --banks Wells,BoFA,USWest,Chase,CapOne \
             --start 2022-01-01 --days 5 --format csv --out ./output
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .profiles import ProfileError, load_bank_profile
from .report_builder import ReportBuilder
from .schema_loader import SchemaError, load_schema
from .writer import VALID_FORMATS, write_report

DEFAULT_SCHEMA = "schema/fr2052a_schema.json"
DEFAULT_OUT = "./output"
DEFAULT_PROFILES = "bank_profiles"


@dataclass
class Config:
    banks: list[str]
    start: date
    days: int
    fmt: str
    out: Path
    schema: Path
    seed: int | None
    profiles: Path


def _parse_banks(value: str) -> list[str]:
    banks = [b.strip() for b in value.split(",") if b.strip()]
    if not banks:
        raise argparse.ArgumentTypeError("--banks must contain at least one name")
    return banks


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--start must be a valid date in YYYY-MM-DD format, got '{value}'"
        )


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--days must be an integer, got '{value}'")
    if n < 1:
        raise argparse.ArgumentTypeError(f"--days must be >= 1, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate",
        description="Generate mock FR 2052a submission data (one file per bank per day).",
    )
    parser.add_argument("--banks", required=True, type=_parse_banks,
                        help="Comma-separated bank names, e.g. Wells,BoFA,Chase")
    parser.add_argument("--start", required=True, type=_parse_date,
                        help="First reporting date (YYYY-MM-DD)")
    parser.add_argument("--days", type=_positive_int, default=1,
                        help="Number of consecutive days (default: 1)")
    parser.add_argument("--format", dest="fmt", choices=VALID_FORMATS, default="csv",
                        help="Output format (default: csv)")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT),
                        help=f"Output directory (default: {DEFAULT_OUT})")
    parser.add_argument("--schema", type=Path, default=Path(DEFAULT_SCHEMA),
                        help=f"Schema file (default: {DEFAULT_SCHEMA})")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible output")
    parser.add_argument("--profiles", type=Path, default=Path(DEFAULT_PROFILES),
                        help=f"Directory of bank profile JSON files "
                             f"(default: {DEFAULT_PROFILES})")
    return parser


def parse_args(argv: list[str] | None = None) -> Config:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return Config(
        banks=ns.banks,
        start=ns.start,
        days=ns.days,
        fmt=ns.fmt,
        out=ns.out,
        schema=ns.schema,
        seed=ns.seed,
        profiles=ns.profiles,
    )


def run(config: Config) -> list[Path]:
    """Execute generation and return the list of written file paths."""
    schema = load_schema(config.schema)
    print(
        f"Loaded schema '{schema.report}' v{schema.version}: "
        f"{len(schema.tables)} tables, {schema.product_count} products, "
        f"{len(schema.fields)} fields."
    )
    print(
        f"Generating {len(config.banks)} bank(s) x {config.days} day(s) "
        f"= {len(config.banks) * config.days} file(s) as {config.fmt} "
        f"into '{config.out}'."
    )

    written: list[Path] = []
    for bank_index, bank in enumerate(config.banks):
        validation = load_bank_profile(config.profiles, bank, schema)
        profile = validation.profile
        for w in validation.warnings:
            print(f"  [profile warning] {bank}: {w}", file=sys.stderr)
        print(f"  loaded profile for {bank}: {profile.description or '(no description)'}")

        # A per-bank RNG derived from the seed keeps each bank's output
        # independent yet reproducible under --seed.
        bank_seed = None if config.seed is None else config.seed + bank_index
        builder = ReportBuilder(schema, random.Random(bank_seed), profile=profile)

        for offset in range(config.days):
            report_date = config.start + timedelta(days=offset)
            rows = builder.build(bank, report_date)
            path = write_report(rows, bank, report_date, config.out, config.fmt,
                                report_name=schema.report)
            written.append(path)
            print(f"  wrote {path.name} ({len(rows)} rows)")

    print(f"Done. {len(written)} file(s) written to '{config.out}'.")
    return written


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        run(config)
    except SchemaError as exc:
        print(f"Schema error: {exc}", file=sys.stderr)
        return 2
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
