#!/usr/bin/env python3
"""Flatten the FR 2052a JSON schema into a CSV for human verification.

Produces one row per (Table, ProductId, Field) with the field's type, required
flag, referenced enumeration, and status. This CSV is a review aid to check the
schema against the PDF; it is not consumed by the application.

Usage:
    python tools/flatten_schema.py [--schema schema/fr2052a_schema.json] \
                                   [--out schema/fr2052a_schema.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def flatten(schema_path: Path, out_path: Path) -> int:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fields = schema["fields"]
    field_sets = schema["field_sets"]

    rows = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Table",
                "SubTable",
                "Prefix",
                "ProductId",
                "ProductDescription",
                "ProductStatus",
                "Field",
                "Type",
                "Required",
                "EnumName",
            ]
        )
        for table in schema["tables"]:
            field_names = field_sets[table["field_set"]]
            for product in table["products"]:
                for field_name in field_names:
                    spec = fields[field_name]
                    writer.writerow(
                        [
                            table["name"],
                            table.get("subtable", ""),
                            table.get("prefix", ""),
                            product["id"],
                            product["description"],
                            product.get("status", ""),
                            field_name,
                            spec.get("type", ""),
                            spec.get("required", False),
                            spec.get("enum", ""),
                        ]
                    )
                    rows += 1
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flatten FR 2052a schema to CSV.")
    parser.add_argument("--schema", type=Path, default=Path("schema/fr2052a_schema.json"))
    parser.add_argument("--out", type=Path, default=Path("schema/fr2052a_schema.csv"))
    args = parser.parse_args(argv)
    rows = flatten(args.schema, args.out)
    print(f"Wrote {rows} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
