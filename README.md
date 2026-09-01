# FR 2052a Mock Data Generator

Generates realistic, internally consistent **mock** submission data for the
Federal Reserve's **FR 2052a** report (Complex Institution Liquidity Monitoring
Report). Output is one combined file per financial entity per reporting day, in
CSV or JSON.

This produces synthetic test data only. No real institution data is used.

## How it works (hybrid design)

The generator combines two layers:

1. **Rule engine (deterministic, schema-valid).** A single schema
   (`schema/fr2052a_schema.json`) drives all output. Every value is guaranteed
   valid: correct enum codes, maturity dates matching buckets, forward-start
   pairing, currency coherence.
2. **Bank profiles (LLM-authored, optional realism).** A per-bank profile biases
   the output toward that institution's real funding shape (a regional bank is
   deposit-heavy; a markets bank is derivatives/repo-heavy). Profiles are
   authored once by an LLM via OpenRouter, then validated against the schema so
   any hallucinated value is dropped before use.

The LLM never generates row data directly — it only produces the profile. Data
generation stays deterministic (`--seed`), fast, free, and always schema-valid.

## Layout

```
schema/fr2052a_schema.json   Source of truth: tables, products, fields, enumerations
schema/fr2052a_schema.csv    Flattened view for human verification
bank_profiles/<Bank>.json    Per-bank funding-shape profiles (required at run time)
fr2052a_mockgen/             Application package
tools/extract_spec.py        One-time PDF -> text/CSV helper (standalone)
tools/flatten_schema.py      Regenerates the flattened schema CSV
tools/generate_profiles.py   One-time LLM profile generator via OpenRouter (standalone)
spec_extracted/              Text/CSV extracted from the PDF (schema source material)
tests/                       pytest suite
```

## Install

```bash
python -m pip install -r requirements.txt
# or, for just the data-generation runtime:
python -m pip install pandas
```

Requires Python 3.10+. The runtime needs only `pandas`. `pdfplumber` (PDF
extraction) and `requests` (LLM profile generation) are needed only for the
standalone `tools/` helpers.

## Generate data

```bash
python -m fr2052a_mockgen.cli --banks Wells,BoFA,USWest,Chase,CapOne --start 2026-02-01 --days 5 --format csv --out ./output
```

This writes 5 banks x 5 days = 25 files named `FR2052a_<BANK>_<YYYYMMDD>.csv`.
Use `--format json` for JSON output. Use `--seed <int>` for reproducible output.

**Each requested bank must have a profile** at `bank_profiles/<Bank>.json`. The
repository ships profiles for Wells, BoFA, USWest, Chase, and CapOne, so the
command above works out of the box. A missing profile is a clear error (exit
code 3).

If installed as a package (`pip install -e .`), the same command is available as
`generate ...`.

### CLI options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--banks` | yes | — | Comma-separated bank names |
| `--start` | yes | — | First reporting date, `YYYY-MM-DD` |
| `--days` | no | `1` | Number of consecutive days |
| `--format` | no | `csv` | `csv` or `json` |
| `--out` | no | `./output` | Output directory (created if missing) |
| `--schema` | no | `schema/fr2052a_schema.json` | Schema file |
| `--profiles` | no | `bank_profiles` | Directory of per-bank profile JSON files |
| `--seed` | no | none | Random seed for reproducibility |

Exit codes: `0` success, `2` schema error, `3` profile error (e.g. a requested
bank has no profile).

## Output

Each file contains rows from all 13 FR 2052a data tables in one flat structure.
Leading columns are `Table, SubTable, ReportingEntity, ReportDate, Product`,
followed by the union of all table fields. Fields that do not apply to a given
product are left empty.

- **CSV**: single combined table.
- **JSON**: `{ report, reportingEntity, reportDate, rowCount, rows: [...] }`.

Monetary values are expressed in millions, per the FR 2052a instructions.

## Bank profiles (LLM-authored realism)

A profile biases the generator toward a bank's real funding shape. Format:

```json
{
  "bank": "Wells",
  "description": "deposit-funded retail/commercial bank",
  "table_weights":   { "O.D": 4.0, "S.DC": 0.6 },
  "product_weights": { "O.D.1": 5.0 },
  "amount_scale":    { "O.D": 3.0 },
  "counterparty_distribution": { "O.D": { "Retail": 6.0, "Small Business": 3.0 } },
  "collateral_distribution":   { "I.A": { "A-1-Q": 4.0, "G-2-Q": 2.0 } }
}
```

- `table_weights` / `product_weights` bias how many rows each table/product gets.
- `amount_scale` multiplies monetary magnitudes per table (bank size).
- `counterparty_distribution` / `collateral_distribution` weight which enum
  values are chosen for a table.

All sections are optional. Unknown product IDs, counterparties, or collateral
classes are dropped during validation (reported as warnings), so a profile can
never produce schema-invalid data.

### Generating profiles with an LLM (OpenRouter)

1. Copy the env template and add your key (the `.env` file is gitignored):
   ```bash
   cp .env.example .env
   # edit .env: OPENROUTER_API_KEY=sk-or-...
   ```
   `.env` supplies `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, and
   `OPENROUTER_MODEL` (e.g. `google/gemma-4-26b-a4b-it`).
2. Install the profile-generation dependency and run the tool:
   ```bash
   python -m pip install requests
   python tools/generate_profiles.py --banks Wells,BoFA,USWest,Chase,CapOne
   ```
   This writes validated `bank_profiles/<Bank>.json` files. `generate_profiles.py`
   is a standalone helper; the application never imports it, and no API key is
   needed to *generate data* — only to *author profiles*.

You can also edit profiles by hand; they are plain JSON validated at load time.

#### Choosing a model

The profile generator only needs a model that reliably returns a JSON object.
Verified working: `google/gemma-4-26b-a4b-it` and `deepseek/deepseek-v3.2`.

Cautions learned in practice:
- **Avoid `:free` model variants** (e.g. `google/gemma-4-26b-a4b-it:free`) for
  batch runs. They are rate-limited upstream and return HTTP 429.
- **Avoid pure reasoning models** that may return empty `content` (observed with
  `deepseek/deepseek-v4-flash-0731`). If you see "Model returned empty content,"
  switch models.
- **Open a fresh terminal** before running. An `OPENROUTER_MODEL` value already
  set in your shell environment takes precedence over `.env` (the loader never
  overwrites existing environment variables), so a stale session value can
  silently override your `.env` choice.
- Use `--timeout <seconds>` if a model is slow; the request uses a 10s connect
  timeout and the given read timeout.

## Updating the schema (no code changes needed)

The generator is fully schema-driven. To correct or extend enumerations,
products, or fields, edit `schema/fr2052a_schema.json` and regenerate — no code
changes are required.

1. Edit `schema/fr2052a_schema.json` (e.g. add a currency, fix a product
   description, change an allowed value).
2. Regenerate the verification CSV:
   ```bash
   python tools/flatten_schema.py
   ```
3. Regenerate data as usual.

Items still to be verified against the PDF are marked with `"status": "TO_VERIFY"`
in the schema. See `SCHEMA_NOTES.md`.

## Re-running PDF extraction

The schema was authored from text/CSV extracted from the FR 2052a instructions
PDF. To re-extract (e.g. for a newer form version):

```bash
python -m pip install pdfplumber
python tools/extract_spec.py FR_2052a20220429_f.pdf --out spec_extracted
```

`extract_spec.py` is a standalone helper; the application never imports it.

## Phase 2 — Liquidity Surveillance Analytics (`fr2052a_analytics`)

Phase 1 *produces* mock FR 2052a submissions. Phase 2 *consumes* them: a
supervisory-style analytics engine that computes liquidity metrics, evaluates a
declarative rule engine, and runs trend, anomaly, peer-comparison, and an
experimental forecast — surfaced via a CLI report and a Streamlit dashboard.

> All analysis runs on synthetic data. Metrics are **documented approximations**
> of Regulation WW (LCR/NSFR) applied to FR 2052a fields, not exact regulatory
> calculations. Forecasts are experimental. See `ANALYTICS_NOTES.md` for every
> formula and caveat.

### Analyze generated data

```bash
python -m fr2052a_analytics.cli --input ./output --out ./analysis --format json --forecast-days 3
```

This loads every `FR2052a_*` file in `./output`, computes per-entity/day metrics
(approx LCR, HQLA, stressed outflows, short-term wholesale funding reliance,
insured-deposit share, secured rollover, intercompany trapped liquidity,
downgrade drain), evaluates the rules, and writes a surveillance report. If
installed as a package (`pip install -e .`), the command is also available as
`analyze ...`.

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `./output` | Directory of phase-1 output files (CSV or JSON) |
| `--out` | `./analysis` | Report output directory |
| `--format` | `json` | `json` (single file), `csv` (one file per section), or `text` (summary) |
| `--config` | `analytics_config` | Directory of `factors.json` / `rules.json` |
| `--banks` | all | Optional comma-separated subset to analyze |
| `--peers` | all | Optional peer set for comparison |
| `--forecast-days` | `0` | Experimental: days to project key metrics forward (0 = off) |

Exit codes: `0` success, `2` input error (missing/empty data), `3` config error.

### Tune metrics and rules without code changes

The engine is config-driven, mirroring the schema-driven generator:

- `analytics_config/factors.json` — HQLA levels/haircuts, runoff rates, anomaly
  thresholds, forecast method.
- `analytics_config/rules.json` — surveillance rules (metric, operator,
  threshold, severity, message). Add, retune, or disable rules here; changes
  take effect on the next run with no code edits.

### Dashboard (Streamlit UI)

Install the optional UI extra and launch:

```bash
python -m pip install ".[ui]"     # or: pip install streamlit altair
streamlit run fr2052a_analytics/app.py
```

Set the input directory in the sidebar, click **Run analysis**, then explore:
severity overview, per-entity metric time series with an optional experimental
forecast overlay, rule findings, statistical anomalies, peer comparison, and a
business-line breakdown. The core engine stays `pandas`/`numpy`-only; Streamlit
is required only for the dashboard.

## Tests

```bash
python -m pytest
```
