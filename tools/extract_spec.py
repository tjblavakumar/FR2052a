#!/usr/bin/env python3
"""One-time FR 2052a PDF spec extraction helper.

STANDALONE utility. This script is NOT imported by the application runtime.
It converts the FR 2052a instructions PDF into text and per-page table CSVs so
the schema (schema/fr2052a_schema.json) can be authored/verified from the real
source content.

Usage:
    pip install pdfplumber
    python tools/extract_spec.py FR_2052a20220429_f.pdf --out spec_extracted

Outputs (under --out):
    full_text.txt                  full document text, one page section each
    page_<NNN>_table<K>.csv        each detected table on each page

Notes:
    Table extraction on a ~250-page document is imperfect (merged/multi-line
    cells, footnotes). Expect manual cleanup when authoring the schema.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def extract(pdf_path: Path, out_dir: Path) -> dict:
    try:
        import pdfplumber  # imported lazily so the app never needs it
    except ImportError:
        sys.exit(
            "pdfplumber is required for extraction.\n"
            "Install it with: pip install pdfplumber"
        )

    if not pdf_path.is_file():
        sys.exit(f"PDF not found: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    text_path = out_dir / "full_text.txt"

    pages = 0
    tables = 0
    with pdfplumber.open(str(pdf_path)) as pdf, text_path.open(
        "w", encoding="utf-8"
    ) as text_out:
        for page_index, page in enumerate(pdf.pages, start=1):
            pages += 1
            text_out.write(f"\n===== PAGE {page_index:03d} =====\n")
            text_out.write(page.extract_text() or "")
            text_out.write("\n")

            for table_index, table in enumerate(page.extract_tables(), start=1):
                if not table:
                    continue
                tables += 1
                csv_path = out_dir / f"page_{page_index:03d}_table{table_index}.csv"
                with csv_path.open("w", encoding="utf-8", newline="") as csv_out:
                    writer = csv.writer(csv_out)
                    for row in table:
                        writer.writerow(["" if c is None else c for c in row])

    return {"pages": pages, "tables": tables, "text_file": str(text_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract FR 2052a PDF to text/CSV.")
    parser.add_argument("pdf", type=Path, help="Path to the FR 2052a PDF file")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("spec_extracted"),
        help="Output directory (default: spec_extracted)",
    )
    args = parser.parse_args(argv)

    result = extract(args.pdf, args.out)
    print(
        f"Extracted {result['pages']} pages and {result['tables']} tables "
        f"into '{args.out}'."
    )
    print(f"Full text: {result['text_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
