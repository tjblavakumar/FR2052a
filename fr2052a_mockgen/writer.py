"""Serialize a per-bank/day FR 2052a dataset to CSV or JSON.

One combined file is produced per (bank, date). The CSV form is a single flat
table with a stable column order (tag columns first, then the union of all
fields across tables). The JSON form is a structured record with metadata.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .report_builder import TAG_ENTITY, TAG_REPORT_DATE, TAG_SUBTABLE, TAG_TABLE

# Columns that lead every output file, in this order.
LEADING_COLUMNS = [TAG_TABLE, TAG_SUBTABLE, TAG_ENTITY, TAG_REPORT_DATE, "Product"]

VALID_FORMATS = ("csv", "json")


def file_name(bank: str, report_date: date, fmt: str) -> str:
    """Return the output file name for a bank/date/format."""
    return f"FR2052a_{bank}_{report_date.strftime('%Y%m%d')}.{fmt}"


def _ordered_columns(rows: list[dict]) -> list[str]:
    """Stable column order: leading tags, then remaining keys in first-seen order."""
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    leading = [c for c in LEADING_COLUMNS if c in seen]
    rest = [c for c in seen if c not in leading]
    return leading + rest


def write_report(rows: list[dict], bank: str, report_date: date, out_dir: str | Path,
                 fmt: str, report_name: str = "FR 2052a") -> Path:
    """Write ``rows`` for one bank/day and return the output path.

    Args:
        rows: row dicts from ReportBuilder.build().
        bank: reporting entity token used in the file name.
        report_date: reporting date.
        out_dir: output directory (created if missing).
        fmt: 'csv' or 'json'.
        report_name: report label embedded in JSON output.
    """
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}' (expected one of {VALID_FORMATS})")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / file_name(bank, report_date, fmt)

    columns = _ordered_columns(rows)

    if fmt == "csv":
        frame = pd.DataFrame(rows, columns=columns)
        frame.to_csv(out_path, index=False)
    else:  # json
        # Preserve column order within each record and drop empty keys per row.
        records = [{col: row[col] for col in columns if col in row} for row in rows]
        payload = {
            "report": report_name,
            "reportingEntity": bank,
            "reportDate": report_date.isoformat(),
            "rowCount": len(records),
            "rows": records,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return out_path
