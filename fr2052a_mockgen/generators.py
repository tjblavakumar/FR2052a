"""Per-field value generators for FR 2052a mock data.

Each generator produces a schema-valid value for a single field, driven by the
field's type and (for enums) the referenced enumeration. All randomness flows
through a single ``random.Random`` instance so output is reproducible when a
seed is supplied.
"""
from __future__ import annotations

import random

from .schema_loader import FieldSpec, Schema

# Default monetary bounds (in millions) when a field defines no explicit range.
DEFAULT_MONEY_MIN = 0.0
DEFAULT_MONEY_MAX = 50_000.0


class ValueGenerator:
    """Generates schema-valid values for individual fields."""

    def __init__(self, schema: Schema, rng: random.Random | None = None):
        self.schema = schema
        self.rng = rng or random.Random()

    # --- primitive generators -------------------------------------------------
    def enum(self, enum_name: str) -> str:
        return self.rng.choice(self.schema.enum_values(enum_name))

    def weighted_choice(self, weights: dict[str, float]) -> str:
        """Pick a key from ``weights`` proportionally to its weight."""
        keys = list(weights.keys())
        vals = [max(0.0, float(weights[k])) for k in keys]
        total = sum(vals)
        if total <= 0:
            return self.rng.choice(keys)
        return self.rng.choices(keys, weights=vals, k=1)[0]

    def money(self, minimum: float | None = None, maximum: float | None = None) -> float:
        lo = DEFAULT_MONEY_MIN if minimum is None else float(minimum)
        hi = DEFAULT_MONEY_MAX if maximum is None else float(maximum)
        if hi < lo:
            hi = lo
        # Log-ish spread so most values are modest with occasional large ones.
        value = self.rng.uniform(lo, hi)
        return round(value, 3)

    def percent(self, minimum: float | None = None, maximum: float | None = None) -> float:
        lo = 0.0 if minimum is None else float(minimum)
        hi = 150.0 if maximum is None else float(maximum)
        # FR 2052a risk weights are commonly one of a small set of values.
        common = [0, 20, 50, 100, 150]
        common = [w for w in common if lo <= w <= hi]
        if common and self.rng.random() < 0.85:
            return float(self.rng.choice(common))
        return round(self.rng.uniform(lo, hi), 2)

    # --- field dispatch -------------------------------------------------------
    def value_for(self, spec: FieldSpec) -> object:
        """Generate a value for ``spec`` based on its declared type."""
        if spec.type == "enum":
            assert spec.enum is not None
            return self.enum(spec.enum)
        if spec.type == "money":
            return self.money(spec.min, spec.max)
        if spec.type == "percent":
            return self.percent(spec.min, spec.max)
        if spec.type == "string":
            return self._string_value(spec)
        if spec.type == "date":
            # Bare dates are handled by the report builder (needs report date
            # for consistency); default to empty here.
            return ""
        raise ValueError(f"Unsupported field type '{spec.type}'")

    # --- string field heuristics ----------------------------------------------
    _BUSINESS_LINES = [
        "Treasury",
        "Retail Banking",
        "Commercial Banking",
        "Prime Brokerage",
        "Markets",
        "Wealth Management",
    ]

    def _string_value(self, spec: FieldSpec) -> str:
        name = spec.name
        if name == "BusinessLine":
            return self.rng.choice(self._BUSINESS_LINES)
        if name == "InternalCounterparty":
            return f"ENTITY-{self.rng.randint(1, 20):02d}"
        if name in ("SubProduct", "SubProduct2"):
            return f"SP-{self.rng.randint(1, 9)}"
        if name in ("CollectionReference", "ProductReference", "SubProductReference"):
            return f"REF-{self.rng.randint(1000, 9999)}"
        # ReportingEntity and Product are set explicitly by the report builder.
        return f"{name}-{self.rng.randint(1, 999)}"
