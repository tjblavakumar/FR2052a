"""Tests for the per-bank/day report builder and its consistency rules."""
from __future__ import annotations

import random
from datetime import date

from fr2052a_mockgen.report_builder import ReportBuilder, _bucket_to_day_range


def _rows(schema, seed=11, bank="Wells", d=date(2022, 1, 1)):
    builder = ReportBuilder(schema, random.Random(seed))
    return builder.build(bank, d)


def test_rows_span_all_tables(schema):
    rows = _rows(schema)
    seen = {(r["Table"], r["SubTable"]) for r in rows}
    expected = {(t.name, t.subtable) for t in schema.tables}
    assert seen == expected


def test_every_row_tagged(schema):
    d = date(2022, 3, 15)
    rows = _rows(schema, bank="BoFA", d=d)
    for r in rows:
        assert r["ReportingEntity"] == "BoFA"
        assert r["ReportDate"] == d.isoformat()
        assert r["Product"]
        assert r["Table"]


def test_maturity_date_on_or_after_report_date(schema):
    d = date(2022, 1, 1)
    rows = _rows(schema, d=d)
    for r in rows:
        md = r.get("MaturityDate")
        if md:
            assert md >= d.isoformat()


def test_maturity_date_matches_bucket(schema):
    d = date(2022, 1, 1)
    rows = _rows(schema, d=d)
    for r in rows:
        bucket = r.get("MaturityBucket")
        md = r.get("MaturityDate")
        if not bucket or not md:
            continue
        rng = _bucket_to_day_range(bucket)
        if rng is None:
            # Open/Perpetual should not carry a concrete date.
            assert md == ""
            continue
        offset = (date.fromisoformat(md) - d).days
        assert rng[0] <= offset <= rng[1]


def test_forward_start_paired(schema):
    rows = _rows(schema)
    for r in rows:
        amt = r.get("ForwardStartAmount")
        if amt not in (None, "") and float(amt) > 0:
            # a positive forward-start amount must carry a bucket if the field exists
            if "ForwardStartBucket" in r:
                assert r["ForwardStartBucket"]


def test_converted_forces_usd(schema):
    rows = _rows(schema)
    for r in rows:
        if r.get("Converted") == "Y":
            assert r["Currency"] == "USD"


def test_internal_counterparty_cleared_when_not_internal(schema):
    rows = _rows(schema)
    for r in rows:
        if "Internal" in r and "InternalCounterparty" in r and r.get("Internal") != "Y":
            assert r["InternalCounterparty"] == ""


def test_bucket_range_helper():
    assert _bucket_to_day_range("Open") is None
    assert _bucket_to_day_range("Perpetual") is None
    assert _bucket_to_day_range("Day 5") == (5, 5)
    assert _bucket_to_day_range("91 - 120 Days") == (91, 120)
    assert _bucket_to_day_range(">5 Yr") == (1826, 3650)
