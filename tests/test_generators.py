"""Tests for per-field value generation."""
from __future__ import annotations

import random

from fr2052a_mockgen.generators import ValueGenerator


def test_enum_values_come_from_schema(schema):
    gen = ValueGenerator(schema, random.Random(1))
    allowed = set(schema.enum_values("Counterparty"))
    for _ in range(50):
        assert gen.enum("Counterparty") in allowed


def test_money_within_bounds(schema):
    gen = ValueGenerator(schema, random.Random(2))
    for _ in range(100):
        v = gen.money(10, 100)
        assert 10 <= v <= 100


def test_money_non_negative_default(schema):
    gen = ValueGenerator(schema, random.Random(3))
    for _ in range(100):
        assert gen.money() >= 0


def test_percent_within_bounds(schema):
    gen = ValueGenerator(schema, random.Random(4))
    for _ in range(100):
        v = gen.percent(0, 150)
        assert 0 <= v <= 150


def test_currency_is_valid(schema):
    gen = ValueGenerator(schema, random.Random(5))
    allowed = set(schema.enum_values("Currency"))
    spec = schema.field_spec("Currency")
    for _ in range(20):
        assert gen.value_for(spec) in allowed


def test_deterministic_under_seed(schema):
    g1 = ValueGenerator(schema, random.Random(42))
    g2 = ValueGenerator(schema, random.Random(42))
    seq1 = [g1.value_for(schema.field_spec("MarketValue")) for _ in range(20)]
    seq2 = [g2.value_for(schema.field_spec("MarketValue")) for _ in range(20)]
    assert seq1 == seq2


def test_value_for_all_fields_runs(schema):
    gen = ValueGenerator(schema, random.Random(6))
    for name in schema.fields:
        gen.value_for(schema.field_spec(name))  # should not raise
