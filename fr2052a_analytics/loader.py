"""Load phase-1 FR 2052a output files into one tidy DataFrame.

This module is the input contract for the analytics engine. It discovers files
named ``FR2052a_<BANK>_<YYYYMMDD>.{csv,json}`` in an input directory, reads both
CSV and JSON forms, and normalizes them into a single long/tidy pandas
DataFrame with a stable set of columns. Downstream stages never need to know
whether a row originated from CSV or JSON.

Normalized frame guarantees:
    * Columns ``ReportingEntity``, ``ReportDate`` (datetime64), ``Table``,
      ``SubTable``, ``Product`` are always present.
    * The union of all field columns seen across files is present; a field
      missing from a given row is NaN (numeric) or empty string (text).
    * Known monetary columns are coerced to numeric (invalid -> NaN).
    * ``SourceFile`` records the originating file name for traceability.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .cli import InputError

# Filename pattern: FR2052a_<BANK>_<YYYYMMDD>.<ext>
_FILENAME_RE = re.compile(r"^FR2052a_(?P<bank>.+)_(?P<date>\d{8})\.(?P<ext>csv|json)$", re.IGNORECASE)

# Columns that identify a row. Always present after normalization.
KEY_COLUMNS = ["ReportingEntity", "ReportDate", "Table", "SubTable", "Product"]

# Monetary / numeric columns coerced to float. Aligned with the schema's
# money-typed fields plus RiskWeight (percent).
NUMERIC_COLUMNS = [
    "MarketValue", "LendableValue", "MaturityAmount", "CollateralValue",
    "ForwardStartAmount", "RiskWeight",
    "MaturityAmountCurrency1", "MaturityAmountCurrency2",
    "ForwardStartAmountCurrency1", "ForwardStartAmountCurrency2",
]


@dataclass
class LoadResult:
    """Result of loading an input directory."""

    frame: pd.DataFrame
    files: list[Path]

    @property
    def entities(self) -> list[str]:
        return sorted(self.frame["ReportingEntity"].dropna().unique().tolist())

    @property
    def dates(self) -> list[pd.Timestamp]:
        return sorted(self.frame["ReportDate"].dropna().unique().tolist())


def parse_filename(name: str) -> tuple[str, pd.Timestamp] | None:
    """Parse ``FR2052a_<BANK>_<YYYYMMDD>.<ext>`` -> (bank, date), or None."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    bank = m.group("bank")
    try:
        dt = pd.to_datetime(m.group("date"), format="%Y%m%d")
    except (ValueError, TypeError):
        return None
    return bank, dt


def discover_files(input_dir: Path, banks: list[str] | None = None) -> list[Path]:
    """Return sorted phase-1 files in ``input_dir``, optionally filtered by bank."""
    if not input_dir.exists():
        raise InputError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise InputError(f"Input path is not a directory: {input_dir}")

    bank_filter = set(banks) if banks else None
    matched: list[Path] = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        parsed = parse_filename(path.name)
        if parsed is None:
            continue
        bank, _ = parsed
        if bank_filter is not None and bank not in bank_filter:
            continue
        matched.append(path)
    return matched


def discover_entities(input_dir: Path) -> list[str]:
    """Return the sorted unique bank names present in ``input_dir`` by scanning
    filenames only (no file contents read). Returns [] if the directory is
    missing or contains no recognizable FR2052a files.
    """
    p = Path(input_dir)
    if not p.exists() or not p.is_dir():
        return []
    names: set[str] = set()
    for path in sorted(p.iterdir()):
        if not path.is_file():
            continue
        parsed = parse_filename(path.name)
        if parsed is not None:
            names.add(parsed[0])
    return sorted(names)


def _read_one(path: Path) -> pd.DataFrame:
    """Read a single CSV or JSON file into a DataFrame of row records."""
    ext = path.suffix.lower()
    if ext == ".csv":
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif ext == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        frame = pd.DataFrame(rows)
    else:
        raise InputError(f"Unsupported file extension for {path.name}")

    if frame.empty:
        return frame

    # Backstop identity columns from the filename in case a file is missing them.
    parsed = parse_filename(path.name)
    if parsed is not None:
        bank, dt = parsed
        if "ReportingEntity" not in frame.columns:
            frame["ReportingEntity"] = bank
        if "ReportDate" not in frame.columns:
            frame["ReportDate"] = dt.strftime("%Y-%m-%d")
    frame["SourceFile"] = path.name
    return frame


def _coerce(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce types: ReportDate -> datetime, numeric cols -> float, text -> str."""
    # ReportDate to datetime (day precision).
    frame["ReportDate"] = pd.to_datetime(frame["ReportDate"], errors="coerce").dt.normalize()

    for col in NUMERIC_COLUMNS:
        if col in frame.columns:
            # Empty strings and non-numeric become NaN.
            frame[col] = pd.to_numeric(
                frame[col].replace("", pd.NA) if frame[col].dtype == object else frame[col],
                errors="coerce",
            )

    # Ensure key identity columns exist.
    for col in KEY_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA

    # Normalize remaining object columns: keep as string, NaN/None -> "".
    numeric_set = set(NUMERIC_COLUMNS) | {"ReportDate"}
    for col in frame.columns:
        if col in numeric_set:
            continue
        if frame[col].dtype == object:
            frame[col] = frame[col].fillna("").astype(str)
    return frame


def load(input_dir: Path, banks: list[str] | None = None) -> LoadResult:
    """Load and normalize all phase-1 files in ``input_dir``.

    Args:
        input_dir: directory containing ``FR2052a_*`` files.
        banks: optional subset of bank names to include.

    Returns:
        LoadResult with a normalized frame and the list of files read.

    Raises:
        InputError: if the directory is missing/empty or no valid files match.
    """
    files = discover_files(input_dir, banks)
    if not files:
        detail = f" for banks {banks}" if banks else ""
        raise InputError(
            f"No FR2052a_*.csv/.json files found in {input_dir}{detail}."
        )

    frames = [f for f in (_read_one(p) for p in files) if not f.empty]
    if not frames:
        raise InputError(f"Input files in {input_dir} contained no rows.")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = _coerce(combined)

    # Stable column order: keys, then the rest alphabetically, SourceFile last.
    rest = sorted(c for c in combined.columns if c not in KEY_COLUMNS and c != "SourceFile")
    ordered = [c for c in KEY_COLUMNS if c in combined.columns] + rest + ["SourceFile"]
    combined = combined[[c for c in ordered if c in combined.columns]]

    return LoadResult(frame=combined, files=files)
