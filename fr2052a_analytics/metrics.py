"""Liquidity metrics engine for FR 2052a data.

Computes, per (ReportingEntity, ReportDate), a set of liquidity metrics from the
normalized frame produced by :mod:`fr2052a_analytics.loader`:

Core metrics (this module, Task 3):
    * ``hqla_stock``            -- approximate stock of high-quality liquid assets
    * ``stress_outflows``       -- approximate stressed 30-day cash outflows
    * ``stress_inflows``        -- approximate stressed 30-day cash inflows (capped)
    * ``net_outflows``          -- outflows minus capped inflows
    * ``approx_lcr``            -- hqla_stock / net_outflows (ratio, %)
    * ``reported_lcr``          -- firm-reported LCR (product S.L.6), for cross-check
    * ``reported_nsfr``         -- firm-reported NSFR (product S.L.10), for cross-check
    * ``lcr_divergence``        -- approx_lcr minus reported_lcr

IMPORTANT: every factor is a documented approximation of Regulation WW (LCR /
NSFR) treatment applied to available FR 2052a fields. These are not exact
regulatory calculations. On synthetic phase-1 data the firm-reported S.L.6 /
S.L.10 values are random magnitudes, not true ratios, so the divergence metric
mainly demonstrates the cross-check mechanism; it becomes meaningful on real
data. See ANALYTICS_NOTES.md.

Derived indicators and the per-business-line slice are added in Task 4.
"""
from __future__ import annotations

import re

import pandas as pd

# Column names in the normalized frame.
ENTITY = "ReportingEntity"
DATE = "ReportDate"
TABLE = "Table"
SUBTABLE = "SubTable"
PRODUCT = "Product"

# Group key for per-entity/day metrics.
GROUP_KEYS = [ENTITY, DATE]

_BUCKET_DAY_RE = re.compile(r"Day (\d+)")


def _amount(frame: pd.DataFrame, col: str) -> pd.Series:
    """Return a numeric column, or a zero series if the column is absent."""
    if col in frame.columns:
        return pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=frame.index)


def hqla_level(collateral_class: str, factors: dict) -> str | None:
    """Return the HQLA level ('L1'/'L2A'/'L2B') for a collateral class, or None.

    Only classes carrying the HQLA suffix (``-Q``) are HQLA-eligible. The level
    is looked up by the alphabetic prefix (e.g. ``A-1-Q`` -> prefix ``A``).
    """
    if not isinstance(collateral_class, str) or not collateral_class:
        return None
    hqla = factors.get("hqla", {})
    suffix = hqla.get("hqla_suffix", "-Q")
    if not collateral_class.endswith(suffix):
        return None
    prefix = collateral_class.split("-", 1)[0]
    return hqla.get("level_by_prefix", {}).get(prefix)


def _short_term_buckets(factors: dict) -> set[str]:
    """Set of MaturityBucket labels considered <= 30 days (plus extras)."""
    buckets_cfg = factors.get("buckets", {})
    day_max = int(buckets_cfg.get("short_term_day_max", 30))
    labels = {f"Day {i}" for i in range(1, day_max + 1)}
    labels.update(buckets_cfg.get("short_term_extra", []))
    return labels


def compute_hqla(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Approximate HQLA stock per entity/day from unencumbered inflow assets.

    Uses Inflows/Assets rows (product prefix ``I.A``) that carry an HQLA-eligible
    collateral class, applies the level haircut to MarketValue, and sums. A
    simplified Level 2 / Level 2B cap is applied at the entity/day level.
    """
    hqla_cfg = factors.get("hqla", {})
    haircuts = hqla_cfg.get("haircut_by_level", {})
    level2_cap = float(hqla_cfg.get("level2_cap", 0.40))
    level2b_cap = float(hqla_cfg.get("level2b_cap", 0.15))

    assets = frame[frame[PRODUCT].astype(str).str.startswith("I.A")].copy()
    if assets.empty:
        return pd.DataFrame(columns=GROUP_KEYS + ["hqla_stock", "hqla_l1", "hqla_l2a", "hqla_l2b"])

    assets["_level"] = assets["CollateralClass"].map(lambda c: hqla_level(c, factors))
    assets = assets[assets["_level"].notna()]
    mv = _amount(assets, "MarketValue")
    assets["_weighted"] = mv * assets["_level"].map(lambda lv: 1.0 - float(haircuts.get(lv, 0.0)))

    def _agg(group: pd.DataFrame) -> pd.Series:
        l1 = group.loc[group["_level"] == "L1", "_weighted"].sum()
        l2a = group.loc[group["_level"] == "L2A", "_weighted"].sum()
        l2b = group.loc[group["_level"] == "L2B", "_weighted"].sum()
        # Simplified caps: L2B capped at level2b_cap of total; L2 (2A+2B) at level2_cap.
        total_pre = l1 + l2a + l2b
        l2b_capped = min(l2b, level2b_cap * total_pre) if total_pre > 0 else 0.0
        l2_total = l2a + l2b_capped
        l2_capped = min(l2_total, level2_cap * total_pre) if total_pre > 0 else l2_total
        stock = l1 + l2_capped
        return pd.Series({
            "hqla_stock": stock,
            "hqla_l1": l1,
            "hqla_l2a": l2a,
            "hqla_l2b": l2b,
        })

    return assets.groupby(GROUP_KEYS, sort=False).apply(_agg, include_groups=False).reset_index()


def _deposit_runoff_rate(row: pd.Series, dep_cfg: dict) -> float:
    """Approximate deposit runoff rate from counterparty / insured / product."""
    product = str(row.get(PRODUCT, ""))
    counterparty = str(row.get("Counterparty", ""))
    insured = str(row.get("Insured", ""))

    # Operational deposit products (O.D.4/O.D.5/O.D.7).
    if product in ("O.D.4", "O.D.5", "O.D.7"):
        return float(dep_cfg.get("operational", 0.25))
    # Brokered (O.D.8).
    if product == "O.D.8":
        return float(dep_cfg.get("brokered", 1.00))
    # Non-operational (O.D.6).
    if product == "O.D.6":
        if counterparty in ("Bank", "Broker-Dealer", "Investment Company or Advisor",
                             "Financial Market Utility", "Non-Regulated Fund"):
            return float(dep_cfg.get("non_operational_financial", 1.00))
        return float(dep_cfg.get("non_operational_nonfinancial", 0.40))

    # Retail / small-business transactional & relationship accounts.
    if counterparty == "Retail":
        if insured == "Y":
            return float(dep_cfg.get("insured_stable", 0.03))
        return float(dep_cfg.get("uninsured_retail", 0.10))
    if counterparty == "Small Business":
        return float(dep_cfg.get("small_business", 0.10))
    return float(dep_cfg.get("default", 0.40))


def compute_outflows(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Approximate stressed 30-day outflows per entity/day.

    Combines deposit runoff (O.D), wholesale funding runoff (O.W), secured
    funding runoff by collateral quality (O.S), and contingent/other (O.O).
    """
    of_cfg = factors.get("outflow_runoff", {})
    dep_cfg = of_cfg.get("deposits", {})
    ws_cfg = of_cfg.get("wholesale", {})
    sec_cfg = of_cfg.get("secured_by_collateral_level", {})
    other_cfg = of_cfg.get("other_contingent", {})

    out = frame[frame[TABLE].astype(str) == "Outflows"].copy()
    if out.empty:
        return pd.DataFrame(columns=GROUP_KEYS + ["stress_outflows"])

    amount = _amount(out, "MaturityAmount")
    rates = pd.Series(0.0, index=out.index)

    is_dep = out[SUBTABLE].astype(str) == "Deposits"
    if is_dep.any():
        rates.loc[is_dep] = out.loc[is_dep].apply(lambda r: _deposit_runoff_rate(r, dep_cfg), axis=1)

    is_ws = out[SUBTABLE].astype(str) == "Wholesale"
    if is_ws.any():
        def _ws_rate(product: str) -> float:
            if product == "O.W.8":  # Commercial Paper
                return float(ws_cfg.get("commercial_paper", 1.00))
            if product in ("O.W.11", "O.W.12"):  # Long-term debt
                return float(ws_cfg.get("long_term_debt", 1.00))
            return float(ws_cfg.get("unsecured_default", 1.00))
        rates.loc[is_ws] = out.loc[is_ws, PRODUCT].astype(str).map(_ws_rate)

    is_sec = out[SUBTABLE].astype(str) == "Secured"
    if is_sec.any():
        def _sec_rate(cc: str) -> float:
            lvl = hqla_level(cc, factors)
            key = lvl if lvl else "non_hqla"
            return float(sec_cfg.get(key, 1.00))
        rates.loc[is_sec] = out.loc[is_sec, "CollateralClass"].astype(str).map(_sec_rate)

    is_other = out[SUBTABLE].astype(str) == "Other"
    if is_other.any():
        def _other_rate(product: str) -> float:
            if product == "O.O.4":  # Credit facilities
                return float(other_cfg.get("credit_facility", 0.10))
            if product == "O.O.5":  # Liquidity facilities
                return float(other_cfg.get("liquidity_facility", 0.30))
            if product in ("O.O.1", "O.O.8", "O.O.20"):  # Derivative-related
                return float(other_cfg.get("derivative_related", 1.00))
            return float(other_cfg.get("default", 0.10))
        rates.loc[is_other] = out.loc[is_other, PRODUCT].astype(str).map(_other_rate)

    out["_weighted_outflow"] = amount.values * rates.values
    grouped = out.groupby(GROUP_KEYS, sort=False)["_weighted_outflow"].sum().reset_index()
    return grouped.rename(columns={"_weighted_outflow": "stress_outflows"})


def compute_inflows(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Approximate stressed 30-day inflows per entity/day (pre-cap).

    Applies inflow recognition rates to maturing secured (I.S) and unsecured
    (I.U) inflows. The LCR inflow cap (75% of outflows) is applied later in
    :func:`compute_core_metrics` where outflows are available.
    """
    in_cfg = factors.get("inflow_rate", {})
    inflows = frame[frame[TABLE].astype(str) == "Inflows"].copy()
    inflows = inflows[inflows[SUBTABLE].astype(str).isin(["Secured", "Unsecured"])]
    if inflows.empty:
        return pd.DataFrame(columns=GROUP_KEYS + ["stress_inflows_precap"])

    amount = _amount(inflows, "MaturityAmount")
    sub = inflows[SUBTABLE].astype(str)
    rate = pd.Series(float(in_cfg.get("default", 0.50)), index=inflows.index)
    rate.loc[sub == "Secured"] = float(in_cfg.get("secured_lending_default", 0.0))
    rate.loc[sub == "Unsecured"] = float(in_cfg.get("unsecured_default", 0.50))

    inflows["_weighted_inflow"] = amount.values * rate.values
    grouped = inflows.groupby(GROUP_KEYS, sort=False)["_weighted_inflow"].sum().reset_index()
    return grouped.rename(columns={"_weighted_inflow": "stress_inflows_precap"})


def compute_reported_ratios(frame: pd.DataFrame) -> pd.DataFrame:
    """Extract firm-reported LCR (S.L.6) and NSFR (S.L.10) per entity/day.

    On synthetic data these MarketValue amounts are random magnitudes rather
    than true ratios; they are surfaced for the cross-check mechanism and become
    meaningful on real submissions.
    """
    sl = frame[frame[PRODUCT].astype(str).isin(["S.L.6", "S.L.10"])].copy()
    if sl.empty:
        return pd.DataFrame(columns=GROUP_KEYS + ["reported_lcr", "reported_nsfr"])
    sl["_val"] = _amount(sl, "MarketValue")
    pivot = sl.pivot_table(index=GROUP_KEYS, columns=PRODUCT, values="_val", aggfunc="first").reset_index()
    pivot = pivot.rename(columns={"S.L.6": "reported_lcr", "S.L.10": "reported_nsfr"})
    for col in ("reported_lcr", "reported_nsfr"):
        if col not in pivot.columns:
            pivot[col] = pd.NA
    return pivot[GROUP_KEYS + ["reported_lcr", "reported_nsfr"]]


def compute_core_metrics(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Assemble the core per-entity/day metrics frame.

    Returns one row per (ReportingEntity, ReportDate) with HQLA, outflow/inflow,
    net outflow, approximate LCR, and firm-reported ratios for cross-check.
    """
    base = frame[GROUP_KEYS].drop_duplicates().reset_index(drop=True)

    hqla = compute_hqla(frame, factors)
    outflows = compute_outflows(frame, factors)
    inflows = compute_inflows(frame, factors)
    reported = compute_reported_ratios(frame)

    metrics = base
    for part in (hqla, outflows, inflows, reported):
        metrics = metrics.merge(part, on=GROUP_KEYS, how="left")

    # Fill numeric gaps.
    for col in ["hqla_stock", "hqla_l1", "hqla_l2a", "hqla_l2b",
                "stress_outflows", "stress_inflows_precap"]:
        if col not in metrics.columns:
            metrics[col] = 0.0
        metrics[col] = pd.to_numeric(metrics[col], errors="coerce").fillna(0.0)

    # Apply LCR inflow cap: recognized inflows <= cap * outflows.
    inflow_cap = float(factors.get("inflow_rate", {}).get("inflow_cap_pct_of_outflows", 0.75))
    metrics["stress_inflows"] = metrics[["stress_inflows_precap", "stress_outflows"]].apply(
        lambda r: min(r["stress_inflows_precap"], inflow_cap * r["stress_outflows"]), axis=1
    )
    metrics["net_outflows"] = (metrics["stress_outflows"] - metrics["stress_inflows"]).clip(lower=0.0)

    # Approximate LCR as a percentage; guard divide-by-zero.
    metrics["approx_lcr"] = metrics.apply(
        lambda r: (100.0 * r["hqla_stock"] / r["net_outflows"]) if r["net_outflows"] > 0 else pd.NA,
        axis=1,
    )

    metrics["lcr_divergence"] = metrics["approx_lcr"] - pd.to_numeric(
        metrics.get("reported_lcr"), errors="coerce"
    )

    metrics = metrics.sort_values(GROUP_KEYS).reset_index(drop=True)
    return metrics


# --------------------------------------------------------------------------
# Derived indicators (Task 4)
#
# These indicators characterize the *shape* of an entity's funding and
# contingent risk, complementing the LCR-style core metrics. Each is a
# documented approximation computed from available FR 2052a fields.
# --------------------------------------------------------------------------


def _sum_by_group(frame: pd.DataFrame, mask: pd.Series, col: str, name: str) -> pd.DataFrame:
    """Sum ``col`` over rows selected by ``mask``, grouped by entity/day."""
    sel = frame[mask]
    if sel.empty:
        return pd.DataFrame(columns=GROUP_KEYS + [name])
    vals = _amount(sel, col)
    tmp = sel[GROUP_KEYS].copy()
    tmp[name] = vals.values
    return tmp.groupby(GROUP_KEYS, sort=False)[name].sum().reset_index()


def compute_derived_indicators(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Compute derived funding / contingent-risk indicators per entity/day.

    Indicators:
        * ``stwf_reliance``          -- short-term wholesale funding / total wholesale
        * ``deposit_total``          -- total deposit funding (O.D)
        * ``insured_deposit_share``  -- insured deposits / total deposits
        * ``wholesale_total``        -- total wholesale funding (O.W)
        * ``secured_rollover``       -- near-term (<=30d) secured funding (O.S)
        * ``secured_total``          -- total secured funding (O.S)
        * ``secured_rollover_share`` -- near-term secured / total secured
        * ``intercompany_trapped``   -- subsidiary liquidity/funding NOT transferable
                                        (S.L.1 + S.L.7)
        * ``intercompany_transferable`` -- available for transfer (S.L.2 + S.L.8)
        * ``intercompany_trapped_share`` -- trapped / (trapped + transferable)
        * ``downgrade_drain``        -- collateral required on downgrade
                                        (O.O.13..O.O.16)
        * ``downgrade_drain_to_hqla`` -- filled later against hqla_stock in
                                         :func:`compute_metrics`
    """
    short_buckets = _short_term_buckets(factors)
    sub = frame[SUBTABLE].astype(str)
    tbl = frame[TABLE].astype(str)
    product = frame[PRODUCT].astype(str)

    # Wholesale funding.
    ws_mask = tbl.eq("Outflows") & sub.eq("Wholesale")
    wholesale_total = _sum_by_group(frame, ws_mask, "MaturityAmount", "wholesale_total")
    if "MaturityBucket" in frame.columns:
        ws_short_mask = ws_mask & frame["MaturityBucket"].astype(str).isin(short_buckets)
    else:
        ws_short_mask = ws_mask & False
    stwf = _sum_by_group(frame, ws_short_mask, "MaturityAmount", "stwf")

    # Deposits.
    dep_mask = tbl.eq("Outflows") & sub.eq("Deposits")
    deposit_total = _sum_by_group(frame, dep_mask, "MaturityAmount", "deposit_total")
    insured_mask = dep_mask & (frame.get("Insured", pd.Series("", index=frame.index)).astype(str) == "Y")
    insured_dep = _sum_by_group(frame, insured_mask, "MaturityAmount", "insured_deposits")

    # Secured funding rollover.
    sec_mask = tbl.eq("Outflows") & sub.eq("Secured")
    secured_total = _sum_by_group(frame, sec_mask, "MaturityAmount", "secured_total")
    if "MaturityBucket" in frame.columns:
        sec_short_mask = sec_mask & frame["MaturityBucket"].astype(str).isin(short_buckets)
    else:
        sec_short_mask = sec_mask & False
    secured_rollover = _sum_by_group(frame, sec_short_mask, "MaturityAmount", "secured_rollover")

    # Intercompany liquidity (Supplemental Liquidity Risk Measurement).
    trapped_mask = product.isin(["S.L.1", "S.L.7"])
    trapped = _sum_by_group(frame, trapped_mask, "MarketValue", "intercompany_trapped")
    transferable_mask = product.isin(["S.L.2", "S.L.8"])
    transferable = _sum_by_group(frame, transferable_mask, "MarketValue", "intercompany_transferable")

    # Downgrade contingent drain (total collateral required on 1/2/3-notch or
    # financial-condition change).
    downgrade_mask = product.isin(["O.O.13", "O.O.14", "O.O.15", "O.O.16"])
    downgrade = _sum_by_group(frame, downgrade_mask, "MaturityAmount", "downgrade_drain")

    base = frame[GROUP_KEYS].drop_duplicates().reset_index(drop=True)
    parts = [wholesale_total, stwf, deposit_total, insured_dep, secured_total,
             secured_rollover, trapped, transferable, downgrade]
    out = base
    for part in parts:
        out = out.merge(part, on=GROUP_KEYS, how="left")

    for col in ["wholesale_total", "stwf", "deposit_total", "insured_deposits",
                "secured_total", "secured_rollover", "intercompany_trapped",
                "intercompany_transferable", "downgrade_drain"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["stwf_reliance"] = (out["stwf"] / out["wholesale_total"].where(out["wholesale_total"] > 0)).fillna(0.0)
    out["insured_deposit_share"] = (out["insured_deposits"] / out["deposit_total"].where(out["deposit_total"] > 0)).fillna(0.0)
    out["secured_rollover_share"] = (out["secured_rollover"] / out["secured_total"].where(out["secured_total"] > 0)).fillna(0.0)
    intercompany_denom = out["intercompany_trapped"] + out["intercompany_transferable"]
    out["intercompany_trapped_share"] = (out["intercompany_trapped"] / intercompany_denom.where(intercompany_denom > 0)).fillna(0.0)

    return out


def compute_metrics(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Full per-entity/day metrics: core + derived indicators.

    This is the primary metrics entry point used by the rule engine, analytics,
    and report stages.
    """
    core = compute_core_metrics(frame, factors)
    derived = compute_derived_indicators(frame, factors)
    metrics = core.merge(derived, on=GROUP_KEYS, how="left")

    # Downgrade drain relative to HQLA (a stress-coverage indicator).
    hqla = pd.to_numeric(metrics.get("hqla_stock"), errors="coerce")
    drain = pd.to_numeric(metrics.get("downgrade_drain"), errors="coerce")
    metrics["downgrade_drain_to_hqla"] = (drain / hqla.where(hqla > 0)).fillna(0.0)

    return metrics.sort_values(GROUP_KEYS).reset_index(drop=True)


# --------------------------------------------------------------------------
# Business-line breakdown (Task 4)
# --------------------------------------------------------------------------

BUSINESS_LINE = "BusinessLine"


def compute_business_line_breakdown(frame: pd.DataFrame, factors: dict) -> pd.DataFrame:
    """Per (entity, date, business_line) HQLA and stressed outflows.

    Rows without a BusinessLine value are grouped under ``"(unassigned)"``.
    Enables the OMB-guide requirement of viewing liquidity risk within
    different business lines. Rolls up to entity totals from
    :func:`compute_outflows` / :func:`compute_hqla`.
    """
    work = frame.copy()
    if BUSINESS_LINE not in work.columns:
        work[BUSINESS_LINE] = ""
    work[BUSINESS_LINE] = work[BUSINESS_LINE].astype(str).replace("", "(unassigned)")

    rows: list[pd.DataFrame] = []
    for bl, sub in work.groupby(BUSINESS_LINE, sort=True):
        hqla = compute_hqla(sub, factors)[GROUP_KEYS + ["hqla_stock"]]
        outflows = compute_outflows(sub, factors)
        merged = hqla.merge(outflows, on=GROUP_KEYS, how="outer")
        if merged.empty:
            continue
        # Ensure both value columns exist and are numeric (no all-NA object
        # columns) before concatenation.
        for col in ("hqla_stock", "stress_outflows"):
            if col not in merged.columns:
                merged[col] = 0.0
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
        merged[BUSINESS_LINE] = bl
        rows.append(merged)

    if not rows:
        return pd.DataFrame(columns=GROUP_KEYS + [BUSINESS_LINE, "hqla_stock", "stress_outflows"])

    out = pd.concat(rows, ignore_index=True, sort=False)
    for col in ("hqla_stock", "stress_outflows"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    cols = GROUP_KEYS + [BUSINESS_LINE, "hqla_stock", "stress_outflows"]
    return out[cols].sort_values(GROUP_KEYS + [BUSINESS_LINE]).reset_index(drop=True)
