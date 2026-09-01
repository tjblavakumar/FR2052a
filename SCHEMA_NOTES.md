# Schema Notes — Verification Against the PDF

The schema (`schema/fr2052a_schema.json`) was authored from text and tables
extracted out of `FR_2052a20220429_f.pdf` (see `spec_extracted/`). This note
records what is confidently sourced and what still warrants a manual check
against the PDF. Items in the schema that are uncertain carry
`"status": "TO_VERIFY"` on the affected product; none are currently flagged, but
the mechanism is available for future edits.

## Confidently sourced from the PDF

- **13 data tables** across Inflows / Outflows / Supplemental (Appendix I,
  "Data Tables", pages 84–86 of the instructions).
- **Full product catalog (147 products)** with descriptions, from the Product
  Definitions section and Table of Contents:
  I.A (7), I.U (8), I.S (10), I.O (9), O.W (19), O.S (11), O.D (15), O.O (22),
  S.DC (21), S.L (10), S.B (6), S.I (6), S.FX (3).
- **Per-table field sets** from the Appendix I data-table diagrams (pages
  84–86). `Currency` and `Converted` are added to every product per the Field
  Definitions note (they were omitted from the figure to simplify it).
- **Maturity Bucket value list** (Appendix IV-a): `Open`, `Day 1`..`Day 60`,
  the weekly buckets `61 - 67 Days` .. `83 - 90 Days`, the 30/90-day buckets,
  the yearly buckets, and `Perpetual`.
- **Counterparty types** (Field Definitions, "Counterparty" and Appendix II-b).
- **Collateral Class / Asset Category codes** (Appendix III), including the
  HQLA `-Q` variants and the non-HQLA codes plus `C-1, P-1, P-2, LC-1, LC-2,
  Z-1`.
- **Accounting Designation, Loss Absorbency** value lists (Field Definitions).

## Items to verify against the PDF (recommended review)

These are areas where the extraction is directionally correct but a careful
reviewer should confirm exact allowed values against the instructions:

1. **Field applicability per product.** The schema applies one field set per
   table (subtable). The PDF's Appendices II-a/II-b/II-c define finer,
   per-product requirements (e.g. which specific products require Sub-Product,
   Counterparty, or Collateral Class, and which counterparty values are
   applicable). If you need product-level field applicability, refine the
   per-product entries and flag adjusted ones `TO_VERIFY`.
2. **EncumbranceType, MaturityOptionality, Trigger, CollateralLevel,
   ForeignExchangeOptionDirection** enumerations were assembled from the field
   definitions narrative and may not be exhaustive. Confirm the complete value
   lists.
3. **Currency list** is a representative ISO subset (USD, EUR, GBP, JPY, CHF,
   CAD, AUD, CNY, HKD, SGD). The report itself accepts any reporting currency;
   extend as needed.
4. **EffectiveMaturityBucket** is modeled as a coarser bucket list; confirm
   whether it should mirror the full Maturity Bucket list for your category.
5. **Maturity Bucket tailoring** (Appendix IV-b) varies by firm category
   (I/II/III/IV and wSTWF thresholds). The generator uses the full value list;
   if you must emulate a specific category's tailored bucket set, restrict the
   `MaturityBucket` enumeration accordingly.

## How to apply corrections

Edit `schema/fr2052a_schema.json`, then run `python tools/flatten_schema.py` to
refresh `schema/fr2052a_schema.csv` for side-by-side review. No application code
changes are required.

## Bank profiles vs. schema

Bank profiles (`bank_profiles/<Bank>.json`) are a *realism* layer, not part of
the regulatory schema. They only bias row counts, amounts, and which valid enum
values are chosen. They cannot introduce new products, counterparties, or
collateral classes — any such reference is dropped during profile validation.
Verifying the schema against the PDF (above) is therefore independent of the
profiles; correcting the schema automatically constrains what profiles can do.
