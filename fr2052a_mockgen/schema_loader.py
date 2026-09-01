"""Load and validate the FR 2052a schema.

The schema (schema/fr2052a_schema.json) is the single source of truth describing
the report's tables, product IDs, field definitions, and enumerations. This
module reads it, validates its internal references, and exposes typed objects
for the generator.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class SchemaError(ValueError):
    """Raised when the schema is malformed or internally inconsistent."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    required: bool = False
    enum: str | None = None
    min: float | None = None
    max: float | None = None
    description: str = ""


@dataclass(frozen=True)
class Product:
    id: str
    description: str
    status: str = "OK"


@dataclass
class Table:
    name: str
    subtable: str
    prefix: str
    field_set: str
    field_names: list[str]
    products: list[Product]

    @property
    def label(self) -> str:
        """Human-readable table label, e.g. 'Inflows / Assets'."""
        return f"{self.name} / {self.subtable}" if self.subtable else self.name


@dataclass
class Schema:
    report: str
    version: str
    enumerations: dict[str, list[str]]
    fields: dict[str, FieldSpec]
    tables: list[Table]
    raw: dict = field(default_factory=dict, repr=False)

    # --- convenience accessors -------------------------------------------------
    def enum_values(self, name: str) -> list[str]:
        try:
            return self.enumerations[name]
        except KeyError as exc:
            raise SchemaError(f"Unknown enumeration '{name}'") from exc

    def field_spec(self, name: str) -> FieldSpec:
        try:
            return self.fields[name]
        except KeyError as exc:
            raise SchemaError(f"Unknown field '{name}'") from exc

    def all_products(self) -> list[tuple[Table, Product]]:
        return [(t, p) for t in self.tables for p in t.products]

    @property
    def product_count(self) -> int:
        return sum(len(t.products) for t in self.tables)


VALID_FIELD_TYPES = {"string", "enum", "money", "percent", "date"}


def load_schema(path: str | Path) -> Schema:
    """Load and validate the schema at ``path``.

    Raises :class:`SchemaError` on any structural or referential problem.
    """
    path = Path(path)
    if not path.is_file():
        raise SchemaError(f"Schema file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"Schema is not valid JSON: {exc}") from exc

    for key in ("report", "enumerations", "fields", "field_sets", "tables"):
        if key not in raw:
            raise SchemaError(f"Schema missing required top-level key '{key}'")

    enumerations: dict[str, list[str]] = raw["enumerations"]
    if not isinstance(enumerations, dict):
        raise SchemaError("'enumerations' must be an object")
    for enum_name, values in enumerations.items():
        if not isinstance(values, list) or not values:
            raise SchemaError(f"Enumeration '{enum_name}' must be a non-empty list")

    # --- fields ---------------------------------------------------------------
    fields: dict[str, FieldSpec] = {}
    for fname, spec in raw["fields"].items():
        ftype = spec.get("type")
        if ftype not in VALID_FIELD_TYPES:
            raise SchemaError(
                f"Field '{fname}' has invalid type '{ftype}' "
                f"(expected one of {sorted(VALID_FIELD_TYPES)})"
            )
        if ftype == "enum":
            enum_ref = spec.get("enum")
            if enum_ref is None:
                raise SchemaError(f"Enum field '{fname}' is missing 'enum' reference")
            if enum_ref not in enumerations:
                raise SchemaError(
                    f"Field '{fname}' references undefined enumeration '{enum_ref}'"
                )
        fields[fname] = FieldSpec(
            name=fname,
            type=ftype,
            required=bool(spec.get("required", False)),
            enum=spec.get("enum"),
            min=spec.get("min"),
            max=spec.get("max"),
            description=spec.get("description", ""),
        )

    # --- field_sets -----------------------------------------------------------
    field_sets: dict[str, list[str]] = raw["field_sets"]
    if not isinstance(field_sets, dict):
        raise SchemaError("'field_sets' must be an object")
    for set_name, field_names in field_sets.items():
        if not isinstance(field_names, list) or not field_names:
            raise SchemaError(f"Field set '{set_name}' must be a non-empty list")
        for field_name in field_names:
            if field_name not in fields:
                raise SchemaError(
                    f"Field set '{set_name}' references undefined field '{field_name}'"
                )

    # --- tables & products ----------------------------------------------------
    tables: list[Table] = []
    seen_product_ids: set[str] = set()
    for entry in raw["tables"]:
        for key in ("name", "field_set", "products"):
            if key not in entry:
                raise SchemaError(f"Table entry missing required key '{key}'")
        set_name = entry["field_set"]
        if set_name not in field_sets:
            raise SchemaError(
                f"Table '{entry.get('prefix', entry['name'])}' references "
                f"undefined field_set '{set_name}'"
            )
        products: list[Product] = []
        for prod in entry["products"]:
            pid = prod.get("id")
            if not pid:
                raise SchemaError(f"Product in table '{set_name}' missing 'id'")
            if pid in seen_product_ids:
                raise SchemaError(f"Duplicate product id '{pid}'")
            seen_product_ids.add(pid)
            products.append(
                Product(
                    id=pid,
                    description=prod.get("description", ""),
                    status=prod.get("status", "OK"),
                )
            )
        tables.append(
            Table(
                name=entry["name"],
                subtable=entry.get("subtable", ""),
                prefix=entry.get("prefix", ""),
                field_set=set_name,
                field_names=list(field_sets[set_name]),
                products=products,
            )
        )

    if not tables:
        raise SchemaError("Schema defines no tables")

    return Schema(
        report=raw["report"],
        version=raw.get("version", ""),
        enumerations=enumerations,
        fields=fields,
        tables=tables,
        raw=raw,
    )
