"""Tests for schema loading and validation."""
from __future__ import annotations

import json

import pytest

from fr2052a_mockgen.schema_loader import SchemaError, load_schema


def test_valid_schema_loads(schema):
    assert schema.report == "FR 2052a"
    assert len(schema.tables) == 13
    assert schema.product_count == 147
    assert len(schema.fields) == 41


def test_every_field_set_field_exists(schema):
    for table in schema.tables:
        for field_name in table.field_names:
            assert field_name in schema.fields


def _write(tmp_path, obj):
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_missing_file(tmp_path):
    with pytest.raises(SchemaError, match="not found"):
        load_schema(tmp_path / "nope.json")


def test_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid", encoding="utf-8")
    with pytest.raises(SchemaError, match="not valid JSON"):
        load_schema(p)


def test_missing_top_level_key(tmp_path):
    p = _write(tmp_path, {"report": "X"})
    with pytest.raises(SchemaError, match="missing required top-level key"):
        load_schema(p)


BASE = {
    "report": "T",
    "enumerations": {"YesNo": ["Y", "N"]},
    "fields": {"Flag": {"type": "enum", "enum": "YesNo"}},
    "field_sets": {"S": ["Flag"]},
    "tables": [{"name": "T", "field_set": "S", "products": [{"id": "T.1"}]}],
}


def test_enum_field_undefined_enum(tmp_path):
    obj = json.loads(json.dumps(BASE))
    obj["fields"]["Flag"]["enum"] = "DoesNotExist"
    with pytest.raises(SchemaError, match="undefined enumeration"):
        load_schema(_write(tmp_path, obj))


def test_field_set_undefined_field(tmp_path):
    obj = json.loads(json.dumps(BASE))
    obj["field_sets"]["S"] = ["Missing"]
    with pytest.raises(SchemaError, match="undefined field"):
        load_schema(_write(tmp_path, obj))


def test_table_undefined_field_set(tmp_path):
    obj = json.loads(json.dumps(BASE))
    obj["tables"][0]["field_set"] = "Nope"
    with pytest.raises(SchemaError, match="undefined field_set"):
        load_schema(_write(tmp_path, obj))


def test_duplicate_product_ids(tmp_path):
    obj = json.loads(json.dumps(BASE))
    obj["tables"][0]["products"] = [{"id": "T.1"}, {"id": "T.1"}]
    with pytest.raises(SchemaError, match="Duplicate product id"):
        load_schema(_write(tmp_path, obj))


def test_invalid_field_type(tmp_path):
    obj = json.loads(json.dumps(BASE))
    obj["fields"]["Flag"] = {"type": "banana"}
    with pytest.raises(SchemaError, match="invalid type"):
        load_schema(_write(tmp_path, obj))
