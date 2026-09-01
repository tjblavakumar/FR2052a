"""Assemble a full, internally consistent FR 2052a dataset for one bank/day.

The builder produces rows across all schema tables for a single reporting
entity and reporting date, applying the consistency rules described in SPEC.md
section 10:

  * MaturityDate (when present) is on or after the ReportDate and matches its
    MaturityBucket.
  * ForwardStartAmount and ForwardStartBucket are populated together.
  * Currency is a valid code; Converted = Y flips reporting currency to USD.
  * Every row is tagged with Table, ReportingEntity, and ReportDate.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from .generators import ValueGenerator
from .profiles import BankProfile
from .schema_loader import Product, Schema, Table

# Tag columns added to every row so all tables coexist in one file.
TAG_TABLE = "Table"
TAG_SUBTABLE = "SubTable"
TAG_ENTITY = "ReportingEntity"
TAG_REPORT_DATE = "ReportDate"
DERIVED_MATURITY_DATE = "MaturityDate"

# How many data elements (rows) to synthesize per product.
DEFAULT_ROWS_PER_PRODUCT = (1, 4)


@dataclass
class BuildConfig:
    rows_per_product: tuple[int, int] = DEFAULT_ROWS_PER_PRODUCT


def _bucket_to_day_range(bucket: str) -> tuple[int, int] | None:
    """Map a MaturityBucket label to an inclusive [min_day, max_day] offset.

    Returns None for non-dated buckets (Open, Perpetual) where no concrete
    maturity date applies.
    """
    if bucket in ("Open", "Perpetual"):
        return None
    if bucket.startswith("Day "):
        n = int(bucket.split(" ")[1])
        return (n, n)
    ranges = {
        "61 - 67 Days": (61, 67),
        "68 - 74 Days": (68, 74),
        "75 - 82 Days": (75, 82),
        "83 - 90 Days": (83, 90),
        "91 - 120 Days": (91, 120),
        "121 - 150 Days": (121, 150),
        "151 - 179 Days": (151, 179),
        "180 - 270 Days": (180, 270),
        "271 - 364 Days": (271, 364),
        ">= 1 Yr <= 2 Yr": (365, 730),
        ">2 Yr <= 3 Yr": (731, 1095),
        ">3 Yr <= 4 Yr": (1096, 1460),
        ">4 Yr <= 5 Yr": (1461, 1825),
        ">5 Yr": (1826, 3650),
    }
    return ranges.get(bucket)


class ReportBuilder:
    """Builds the row set for a single (bank, date) report."""

    def __init__(self, schema: Schema, rng: random.Random | None = None,
                 config: BuildConfig | None = None,
                 profile: BankProfile | None = None):
        self.schema = schema
        self.rng = rng or random.Random()
        self.gen = ValueGenerator(schema, self.rng)
        self.config = config or BuildConfig()
        self.profile = profile

    def build(self, bank: str, report_date: date) -> list[dict]:
        rows: list[dict] = []
        lo, hi = self.config.rows_per_product
        for table in self.schema.tables:
            for product in table.products:
                for _ in range(self._row_count(table, product, lo, hi)):
                    rows.append(self._build_row(table, product, bank, report_date))
        return rows

    def _row_count(self, table: Table, product: Product, lo: int, hi: int) -> int:
        """Number of rows for a product, scaled by the profile weight."""
        base = self.rng.randint(lo, hi)
        if self.profile is None:
            return base
        weight = self.profile.product_weight(product.id, table.prefix)
        # Scale the base count by weight; ensure at least 1 row when weight > 0.
        scaled = base * weight
        count = int(scaled)
        # Fractional remainder becomes a probabilistic extra row (deterministic
        # under seed via self.rng).
        if self.rng.random() < (scaled - count):
            count += 1
        if weight > 0:
            count = max(1, count)
        return count

    # --- single row -----------------------------------------------------------
    def _build_row(self, table: Table, product: Product, bank: str,
                   report_date: date) -> dict:
        row: dict[str, object] = {
            TAG_TABLE: table.name,
            TAG_SUBTABLE: table.subtable,
            TAG_ENTITY: bank,
            TAG_REPORT_DATE: report_date.isoformat(),
        }

        for field_name in table.field_names:
            spec = self.schema.field_spec(field_name)
            if field_name == "ReportingEntity":
                row[field_name] = bank
            elif field_name == "Product":
                row[field_name] = product.id
            else:
                row[field_name] = self._field_value(field_name, spec, table)

        self._apply_consistency(row, report_date)
        self._apply_profile_amounts(row, table)
        return row

    def _field_value(self, field_name: str, spec, table: Table) -> object:
        """Field value, biased by the profile for Counterparty / CollateralClass."""
        if self.profile is not None and spec.type == "enum":
            if field_name == "Counterparty":
                weights = self.profile.counterparty_weights(table.prefix)
                if weights:
                    return self.gen.weighted_choice(weights)
            elif field_name == "CollateralClass":
                weights = self.profile.collateral_weights(table.prefix)
                if weights:
                    return self.gen.weighted_choice(weights)
        return self.gen.value_for(spec)

    def _apply_profile_amounts(self, row: dict, table: Table) -> None:
        """Scale monetary fields by the profile's per-table amount multiplier."""
        if self.profile is None:
            return
        mult = self.profile.amount_multiplier(table.prefix)
        if mult == 1.0:
            return
        for field_name in row:
            spec = self.schema.fields.get(field_name)
            if spec is None or spec.type != "money":
                continue
            val = row[field_name]
            if isinstance(val, (int, float)) and val:
                row[field_name] = round(float(val) * mult, 3)

    # --- consistency rules ----------------------------------------------------
    def _apply_consistency(self, row: dict, report_date: date) -> None:
        # Currency / Converted coherence: if Converted = Y, report in USD.
        if row.get("Converted") == "Y":
            row["Currency"] = "USD"

        # Maturity bucket -> concrete maturity date on/after report date.
        bucket = row.get("MaturityBucket")
        if isinstance(bucket, str) and bucket:
            day_range = _bucket_to_day_range(bucket)
            if day_range is None:
                row[DERIVED_MATURITY_DATE] = ""
            else:
                offset = self.rng.randint(day_range[0], day_range[1])
                row[DERIVED_MATURITY_DATE] = (
                    report_date + timedelta(days=offset)
                ).isoformat()

        # Forward start fields must be populated together and consistent.
        has_fs_amount = "ForwardStartAmount" in row
        has_fs_bucket = "ForwardStartBucket" in row
        if has_fs_amount or has_fs_bucket:
            forward_start = self.rng.random() < 0.25
            if forward_start:
                if has_fs_amount and (not row.get("ForwardStartAmount")):
                    row["ForwardStartAmount"] = self.gen.money(1, 1000)
                if has_fs_bucket:
                    row["ForwardStartBucket"] = self.gen.enum("MaturityBucket")
            else:
                if has_fs_amount:
                    row["ForwardStartAmount"] = 0.0
                if has_fs_bucket:
                    row["ForwardStartBucket"] = ""

        # Internal counterparty only meaningful when Internal = Y.
        if "Internal" in row and row.get("Internal") != "Y" and "InternalCounterparty" in row:
            row["InternalCounterparty"] = ""

        # G-SIB only applies where a counterparty is populated.
        if "GSIB" in row and not row.get("Counterparty"):
            row["GSIB"] = ""
