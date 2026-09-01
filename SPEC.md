# FR 2052a Mock Data Generator — Build Specification

## 1. Overview

Build a Python command-line application that generates realistic, internally consistent **mock** submission data for the Federal Reserve's **FR 2052a** report (Complex Institution Liquidity Monitoring Report). The application is driven by a declarative schema file that describes the report's tables, product IDs, fields, and allowed values.

The app produces **one combined data file per financial entity per reporting day**, in either CSV or JSON.

This is synthetic test data only. No real institution data is used or transmitted.

## 2. Goals & Non-Goals

**Goals**
- A verifiable schema file that captures the FR 2052a structure (tables, product IDs, fields, enumerations).
- A generator that emits schema-valid, internally consistent mock data.
- One combined file per bank per day; e.g., 5 banks x 5 days = 25 files.
- CSV and JSON output support.

**Non-Goals**
- No PDF-parsing logic inside the application. PDF-to-text extraction is a one-time standalone helper script, separate from the app.
- Not an official submission tool; output is not validated against the Fed's real filing system.
- No GUI; CLI only.

## 3. Background (context for the implementer)

- FR 2052a (OMB 7100-0361) collects assets, liabilities, funding activities, and contingent liabilities, consolidated and by material entity subsidiary.
- The report is organized into a small number of **Tables**:
  - **Inflows** (Assets)
  - **Outflows** (Liabilities and Commitments)
  - **Supplemental** (Informational, Derivatives & Collateral, Foreign Exchange, Balance Sheet)
- Each data row is a **Product ID** (hierarchical codes like `I.A.1`, `O.D.12`, `S.I.19`) plus a set of standardized fields.
- The authoritative data dictionary lives in a ~250-page PDF. The exact product catalog and enumerations are extracted from that PDF into `spec_extracted/` (see Section 5), then encoded into the schema file. Items that cannot be confidently determined are flagged `TO_VERIFY`.

## 4. Tech Stack

- Python 3.10+
- `pandas` (data handling, CSV/JSON output)
- `argparse` (CLI)
- `pytest` (tests)
- `pdfplumber` — used **only** by the standalone extraction helper, not by the app runtime.

## 5. Repository Layout

```
fr2052a-mockgen/
├── README.md
├── SCHEMA_NOTES.md
├── requirements.txt
├── pyproject.toml                  # expose `generate` entry point
├── tools/
│   └── extract_spec.py             # one-time PDF -> text/CSV helper (standalone)
├── spec_extracted/                 # output of extract_spec.py (checked in for reference)
│   ├── page_XXX_tableY.csv
│   └── full_text.txt
├── schema/
│   ├── fr2052a_schema.json         # source of truth
│   └── fr2052a_schema.csv          # flattened, for human verification
├── fr2052a_mockgen/
│   ├── __init__.py
│   ├── cli.py                      # argparse entry point
│   ├── schema_loader.py            # load + validate schema
│   ├── generators.py               # per-field value generation
│   ├── report_builder.py           # per-bank/day dataset assembly + consistency
│   └── writer.py                   # CSV/JSON output + file naming
├── output/                         # default output dir (gitignored)
└── tests/
    ├── test_cli.py
    ├── test_schema_loader.py
    ├── test_generators.py
    ├── test_report_builder.py
    ├── test_writer.py
    └── test_end_to_end.py
```

## 6. One-Time PDF Extraction Helper (`tools/extract_spec.py`)

- Standalone script, **not imported by the app**.
- Uses `pdfplumber` to:
  - Dump each page's detected tables to `spec_extracted/page_<NNN>_table<K>.csv`.
  - Dump full document text to `spec_extracted/full_text.txt`.
- Usage: `python tools/extract_spec.py <path-to-pdf> [--out spec_extracted]`.
- Must run without crashing and produce non-empty outputs. Table extraction quality on a 250-page doc will be imperfect; that's expected and handled by manual schema authoring in Section 7.

## 7. Schema File (source of truth)

### 7.1 `schema/fr2052a_schema.json`
Authored from `spec_extracted/`. Structure:

```json
{
  "report": "FR 2052a",
  "version": "2022-04-29",
  "enumerations": {
    "Currency": ["USD", "EUR", "GBP", "JPY", "..."],
    "MaturityBucket": ["Open", "Day 1", "Day 2-7", "..."],
    "CollateralClass": ["A-0-Q", "..."],
    "CounterpartyType": ["..."],
    "EncumbranceType": ["..."],
    "YesNo": ["Y", "N"]
  },
  "fields": {
    "Currency":      { "type": "enum", "enum": "Currency", "required": true },
    "Converted":     { "type": "enum", "enum": "YesNo",    "required": true },
    "ReportingEntity": { "type": "string", "required": true },
    "Counterparty":  { "type": "enum", "enum": "CounterpartyType", "required": false },
    "ProductId":     { "type": "string", "required": true },
    "SubProduct":    { "type": "string", "required": false },
    "MarketValue":   { "type": "money", "required": false, "min": 0 },
    "LendableValue": { "type": "money", "required": false, "min": 0 },
    "MaturityAmount":{ "type": "money", "required": false, "min": 0 },
    "MaturityBucket":{ "type": "enum", "enum": "MaturityBucket", "required": false },
    "MaturityDate":  { "type": "date", "required": false },
    "CollateralClass": { "type": "enum", "enum": "CollateralClass", "required": false },
    "Rehypothecated": { "type": "enum", "enum": "YesNo", "required": false },
    "ForwardStartAmount": { "type": "money", "required": false, "min": 0 },
    "ForwardStartBucket": { "type": "enum", "enum": "MaturityBucket", "required": false },
    "EncumbranceType": { "type": "enum", "enum": "EncumbranceType", "required": false },
    "Internal":      { "type": "enum", "enum": "YesNo", "required": false },
    "BusinessLine":  { "type": "string", "required": false }
  },
  "tables": [
    {
      "name": "Inflows",
      "products": [
        { "id": "I.A.1", "description": "...", "fields": ["Currency","Converted","ReportingEntity","ProductId","MarketValue","MaturityBucket","MaturityDate","CollateralClass"], "status": "OK" }
      ]
    },
    { "name": "Outflows", "products": [] },
    { "name": "Supplemental", "products": [] }
  ]
}
```

Rules:
- Each product's `fields` list references keys in the top-level `fields` map.
- Each `enum`-typed field references a key in `enumerations`.
- Ambiguous/unverified products, fields, or enum values carry `"status": "TO_VERIFY"`.

### 7.2 `schema/fr2052a_schema.csv`
Flattened for human verification. One row per (Table, ProductId, Field) with columns:
`Table, ProductId, ProductDescription, Field, Type, Required, EnumName, Status`.
Generated from the JSON.

## 8. CLI Specification

Command: `generate`

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--banks` | comma-separated list | yes | — | e.g. `Wells,BoFA,USWest,Chase,CapOne` |
| `--start` | date `YYYY-MM-DD` | yes | — | first reporting day |
| `--days` | positive int | no | `1` | number of consecutive days |
| `--format` | `csv` \| `json` | no | `csv` | output format |
| `--out` | path | no | `./output` | output directory (created if missing) |
| `--schema` | path | no | `schema/fr2052a_schema.json` | schema file to use |
| `--seed` | int | no | none | RNG seed for reproducible output |

Validation:
- `--start` must parse as a valid date; otherwise exit with clear error.
- `--format` must be `csv` or `json`.
- `--days` must be >= 1.
- `--banks` must be non-empty after splitting/trimming.

On run, print a resolved-config summary and, after generation, a summary (files written, rows per file).

## 9. Output Specification

- One file **per bank per day**. Total files = `len(banks) * days`.
- File name: `FR2052a_<BANK>_<YYYYMMDD>.<ext>` (ext = `csv` or `json`). `<BANK>` is the bank token as passed.
- **CSV**: a single combined table containing rows from all report tables. Columns = the union of all fields plus `Table`, `ReportingEntity`, `ReportDate`. Each row includes a `Table` value (`Inflows` / `Outflows` / `Supplemental`) and its `ProductId`. Fields not applicable to a given product are left empty.
- **JSON**: structured records:
  ```json
  {
    "report": "FR 2052a",
    "reportingEntity": "Wells",
    "reportDate": "2022-01-01",
    "rows": [
      { "Table": "Inflows", "ProductId": "I.A.1", "Currency": "USD" }
    ]
  }
  ```

## 10. Data Generation Rules

**Per-field generation** (driven by field `type`):
- `enum`: pick a value from the referenced enumeration.
- `date`: valid calendar date (see consistency rules).
- `money`: positive number within realistic magnitude bounds (respect `min`/`max` if present).
- `string`: schema/product-appropriate token; `ReportingEntity` = the bank name; `ProductId` = the product's id.
- `YesNo`: `Y` or `N`.

**Internal consistency rules** (must hold within each generated file):
1. `MaturityDate`, when present, is on or after `ReportDate`.
2. `MaturityBucket`, when present, is consistent with `MaturityDate` relative to `ReportDate` (bucket boundaries defined in the schema enumeration).
3. `ForwardStartAmount`/`ForwardStartBucket` are populated together and consistent.
4. `Currency` is a valid enum value; if `Converted` = `Y`, treat amounts as USD-converted consistently.
5. Every row carries the correct `Table`, `ReportingEntity` (= bank), and `ReportDate`.
6. Monetary amounts are non-negative and within configured bounds; per-table totals should roll up to plausible magnitudes.
- With `--seed` set, output is deterministic.

## 11. Component Responsibilities

- `schema_loader.py`: read + validate JSON schema; expose tables → products → fields and enum lookups; fail fast on malformed schema (invalid JSON, product referencing an undefined table/field, field referencing an undefined enum, duplicate product IDs).
- `generators.py`: pure per-field value generators keyed by type/enum, honoring bounds and seed.
- `report_builder.py`: assemble the full row set for one (bank, date); apply consistency rules; tag rows.
- `writer.py`: serialize a (bank, date) dataset to CSV or JSON with correct file naming; ensure output dir exists.
- `cli.py`: parse/validate args, load schema, loop over banks x days, call builder + writer, print summaries.

## 12. Testing Requirements

Use `pytest`. Each component has unit tests; add an end-to-end test.
- `test_cli.py`: arg parsing/validation (bad date, bad format, days<1, empty banks, defaults).
- `test_schema_loader.py`: valid load; malformed JSON; product→undefined table/field; field→undefined enum; duplicate product IDs.
- `test_generators.py`: enum values come from schema; money >= min and non-negative; valid currency/date; determinism under seed.
- `test_report_builder.py`: no maturity date before report date; bucket matches date; forward-start paired; every row tagged with correct Table/bank/date.
- `test_writer.py`: correct filename; CSV columns/header; JSON round-trips to expected records.
- `test_end_to_end.py`: 5 banks x 5 days into a temp dir → exactly 25 files, correct names, non-empty valid content; clean up temp files.

## 13. Acceptance Criteria

1. `python tools/extract_spec.py <pdf>` produces non-empty files in `spec_extracted/`.
2. `schema/fr2052a_schema.json` loads and validates; `schema/fr2052a_schema.csv` lists tables, product IDs, fields, and allowed values for human verification; unverified items are flagged `TO_VERIFY`.
3. `generate --banks Wells,BoFA,USWest,Chase,CapOne --start 2022-01-01 --days 5 --format csv --out ./output` creates exactly 25 files named `FR2052a_<BANK>_<YYYYMMDD>.csv`.
4. The same command with `--format json` creates 25 valid JSON files.
5. Generated data satisfies all consistency rules in Section 10.
6. `--seed` yields reproducible output.
7. `pytest` passes.
8. `README.md` documents install, extraction, generation (CSV + JSON), how to update `TO_VERIFY` enumerations without code changes, and how to re-run extraction. `SCHEMA_NOTES.md` lists items to verify against the PDF.

## 14. Implementation Order

1. Scaffold + CLI skeleton (config parse/validate/echo).
2. `tools/extract_spec.py`; run it; populate `spec_extracted/`.
3. Author `schema/fr2052a_schema.json` from extracted spec; generate `.csv` companion.
4. `schema_loader.py` + validation; wire into CLI (print counts).
5. `generators.py` (single valid values).
6. `report_builder.py` (one bank/day, consistent).
7. `writer.py` (CSV/JSON + naming).
8. End-to-end wiring (banks x days) + run summary.
9. Docs + full verification pass.
