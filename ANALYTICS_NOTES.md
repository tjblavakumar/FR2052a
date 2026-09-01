# Analytics Notes — Metric Definitions & Approximation Caveats

This note documents how the phase-2 liquidity surveillance engine
(`fr2052a_analytics`) computes each metric, which FR 2052a fields it uses, and
where a value is a **documented approximation** rather than an exact Regulation
WW (LCR/NSFR) calculation.

> **All analysis runs on synthetic data.** The engine consumes the phase-1 mock
> generator's output. Numbers here demonstrate the *mechanism*; they do not
> represent any real institution. The metric and rule layer is defined by the
> FR 2052a structure, so it stays valid when the same engine is later pointed at
> real submissions.

## Pipeline

```
loader -> metrics (core + derived) + business-line breakdown
       -> rule engine (findings)
       -> trend / anomaly / peer / forecast
       -> report (json | csv | text)  and  Streamlit UI
```

All factors live in `analytics_config/factors.json`; all rules in
`analytics_config/rules.json`. Both are editable without code changes.

## Core metrics (`metrics.py`)

### HQLA stock — `hqla_stock`
Approximate stock of High-Quality Liquid Assets. Taken from Inflows/Assets rows
(`I.A.*`) whose `CollateralClass` carries the HQLA suffix `-Q`. Each asset's
`MarketValue` is weighted by a level haircut and summed, then simplified Level 2
/ Level 2B caps are applied.

- Level by collateral-class prefix: `A`,`G`,`CB` → L1; `S`,`IG` → L2A; `E` → L2B.
- Haircuts: L1 0%, L2A 15%, L2B 50%.
- Caps: Level 2B ≤ 15% of total, Level 2 (2A+2B) ≤ 40% of total.

*Approximation:* real LCR HQLA eligibility depends on additional operational and
concentration criteria not modeled here; caps are applied at the entity/day
level rather than the exact regulatory formula.

### Stressed outflows — `stress_outflows`
Approximate 30-day stressed cash outflows. Runoff rates are applied to
`MaturityAmount` on Outflows rows:

- **Deposits (`O.D`)**: rate by counterparty/insured/product — insured stable
  retail 3%, uninsured retail / small business 10%, operational 25%,
  non-operational financial 100% / non-financial 40%, brokered 100%.
- **Wholesale (`O.W`)**: commercial paper / long-term debt / other unsecured 100%.
- **Secured (`O.S`)**: by pledged-collateral quality — L1 0%, L2A 15%, L2B 50%,
  non-HQLA 100%.
- **Other/contingent (`O.O`)**: credit facility 10%, liquidity facility 30%,
  derivative-related 100%, default 10%.

*Approximation:* LCR outflow categories are far more granular; these rates are
representative stand-ins keyed to the fields the schema exposes.

### Stressed inflows — `stress_inflows` / net outflows — `net_outflows`
Inflow recognition applied to maturing secured (`I.S`, 0%) and unsecured (`I.U`,
50%) inflows, then capped at 75% of outflows (the LCR inflow cap).
`net_outflows = max(stress_outflows − stress_inflows, 0)`.

### Approximate LCR — `approx_lcr`
`approx_lcr = 100 × hqla_stock / net_outflows` (percent), or empty when
`net_outflows == 0`.

> **Synthetic-data note:** on the mock data `approx_lcr` lands around 8–14%,
> well below the 100% regulatory floor. This is expected: the generator emits
> roughly uniform row counts across all 13 tables, so modeled outflows dwarf the
> HQLA-eligible slice of inflow assets. It is a property of the synthetic data
> shape, **not** a defect in the metric — the value still moves day to day, which
> is what makes trend, anomaly, and rule logic demonstrable. On a real balance
> sheet the HQLA/outflow mix is very different.

### Firm-reported ratios — `reported_lcr` (S.L.6), `reported_nsfr` (S.L.10)
Read directly from the reported supplemental products for cross-checking against
the computed approximation. `lcr_divergence = approx_lcr − reported_lcr`.

> **Synthetic-data note:** in the mock data S.L.6 / S.L.10 carry random
> `MarketValue` magnitudes, not true ratio values. So `lcr_divergence` here only
> demonstrates the cross-check *mechanism*; it becomes meaningful when real
> reported ratios are present.

## Derived indicators (`metrics.py`)

| Metric | Definition | Source |
|--------|------------|--------|
| `stwf_reliance` | short-term (≤30d) wholesale ÷ total wholesale | `O.W` + `MaturityBucket` |
| `insured_deposit_share` | insured deposits ÷ total deposits | `O.D` + `Insured` |
| `secured_rollover_share` | near-term (≤30d) secured ÷ total secured | `O.S` + `MaturityBucket` |
| `intercompany_trapped_share` | (S.L.1+S.L.7) ÷ (S.L.1+S.L.7+S.L.2+S.L.8) | `S.L` |
| `downgrade_drain` | collateral required on downgrade | `O.O.13`–`O.O.16` |
| `downgrade_drain_to_hqla` | `downgrade_drain` ÷ `hqla_stock` | derived |

`intercompany_trapped_share` reflects the OMB guide's concern about liquidity
that cannot move across legal entities; `downgrade_drain` captures contingent
collateral calls under rating stress.

## Business-line breakdown (`metrics.py`)
`hqla_stock` and `stress_outflows` recomputed per `BusinessLine`, addressing the
requirement to see liquidity risk within business lines (e.g. markets vs.
retail). Rows with no business line are grouped as `(unassigned)`.

## Rule engine (`rules.py`, `analytics_config/rules.json`)
Each rule compares one metric against a threshold with an operator
(`lt/le/gt/ge/eq/ne/between/outside`) and emits a `Finding` with a severity
(`info < low < medium < high < critical`) and a message template. Add, retune,
or disable rules by editing `rules.json`; no code changes required. A rule that
references an absent metric is skipped so config can outlive schema changes.

## Trend & anomaly (`trend.py`, `anomaly.py`)
- **Trend:** per (entity, metric) least-squares slope per day, first/last, total
  and average daily change, latest delta, and direction (up/down/flat).
- **Anomaly (all explainable, no ML):** z-score beyond a threshold, IQR fence,
  and day-over-day percentage jump. Thresholds in
  `factors.json → analytics.anomaly`. Distribution detectors need ≥ `min_points`
  observations; the day-over-day detector needs only two.

## Peer comparison (`peer.py`)
For a chosen date (latest by default), each entity's metric value is ranked
within the peer group: peer median/quartiles and the entity's percentile rank.
Requires ≥ 2 entities on that date.

## Forecast (`forecast.py`) — EXPERIMENTAL
A deliberately simple short-horizon projection (linear least-squares trend or
trailing moving average). **Every forecast point is flagged
`experimental=True`.** It illustrates directional movement only; on synthetic
data it reflects the generator's statistical shape, not market behavior. Series
shorter than `min_points` are skipped.

## Extending / tuning
- Edit `analytics_config/factors.json` to change HQLA levels/haircuts, runoff
  rates, anomaly thresholds, or forecast method.
- Edit `analytics_config/rules.json` to change surveillance thresholds/severity.
- Neither requires touching Python code.
