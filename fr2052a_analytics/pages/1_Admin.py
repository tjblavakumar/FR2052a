"""Admin console (Streamlit multi-page).

Streamlit auto-discovers pages in a ``pages/`` directory next to the main app
script (``fr2052a_analytics/Dashboard.py``). This page provides three tabs:

    * Generate data     — run the phase-1 generator into the output folder.
    * Analytics config   — edit factors.json / rules.json.
    * Bank profiles      — edit per-bank funding-shape profiles.

All file operations delegate to :mod:`fr2052a_analytics.admin_service` (which is
Streamlit-free and unit-tested). Every write validates before saving, backs up
the previous file with a timestamped ``.bak``, writes atomically, and clears the
dashboard's pipeline cache so the main page reflects the change.

This is a LOCAL admin tool with no authentication. Synthetic data only.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from fr2052a_analytics import admin_service as adm
from fr2052a_analytics.cli import ConfigError
from fr2052a_mockgen.profiles import ProfileError
from fr2052a_mockgen.schema_loader import SchemaError, load_schema

DEFAULT_CONFIG = "analytics_config"
DEFAULT_PROFILES = "bank_profiles"
DEFAULT_SCHEMA = "schema/fr2052a_schema.json"
DEFAULT_OUTPUT = "./output"
SEVERITIES = ["info", "low", "medium", "high", "critical"]


@st.cache_resource(show_spinner=False)
def _load_schema_cached(schema_path: str):
    return load_schema(schema_path)


def _invalidate() -> None:
    """Clear the dashboard's cached pipeline so edits take effect there."""
    try:
        st.cache_data.clear()
    except Exception:
        pass


def _dist_editor(label: str, mapping: dict) -> dict:
    """Render a two-column key/weight data editor and return the edited dict."""
    rows = [{"key": k, "weight": float(v)} for k, v in (mapping or {}).items()]
    if not rows:
        rows = [{"key": "", "weight": 0.0}]
    edited = st.data_editor(
        pd.DataFrame(rows), num_rows="dynamic", use_container_width=True,
        key=f"editor_{label}", hide_index=True,
    )
    out: dict[str, float] = {}
    for _, r in edited.iterrows():
        k = str(r.get("key", "")).strip()
        if not k:
            continue
        try:
            out[k] = float(r.get("weight", 0.0))
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------

st.set_page_config(page_title="Admin — FR 2052a", layout="wide")
st.title("Admin console")
st.caption(
    "Local admin tools — no authentication. Edits validate before saving, back up "
    "the previous file (timestamped .bak beside the original), write atomically, "
    "and clear the dashboard cache. Synthetic data only."
)

with st.sidebar:
    st.header("Paths")
    config_dir = st.text_input("Config directory", DEFAULT_CONFIG)
    profiles_dir = st.text_input("Profiles directory", DEFAULT_PROFILES)
    schema_path = st.text_input("Schema file", DEFAULT_SCHEMA)
    output_dir = st.text_input("Output directory", DEFAULT_OUTPUT)

tab_gen, tab_cfg, tab_prof = st.tabs(["Generate data", "Analytics config", "Bank profiles"])


# === Tab 1: Generate data ==================================================
with tab_gen:
    st.subheader("Generate mock data")
    available = adm.list_profiles(profiles_dir)
    if not available:
        st.warning(f"No bank profiles found in '{profiles_dir}'.")
    banks = st.multiselect("Banks", available, default=available)
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("Start date", value=date.today())
    days = c2.number_input("Days", min_value=1, value=5, step=1)
    fmt = c3.selectbox("Format", ["csv", "json"])

    c4, c5 = st.columns(2)
    use_seed = c4.checkbox("Use seed (reproducible)", value=True)
    seed_val = c5.number_input("Seed", min_value=0, value=42, step=1, disabled=not use_seed)

    clear_output = st.checkbox("Clear existing output files first", value=False)
    if clear_output:
        st.warning(
            f"This deletes all FR2052a_*.csv / FR2052a_*.json files in '{output_dir}' "
            "before generating."
        )
        confirm_clear = st.checkbox("Yes, delete existing files")
    else:
        confirm_clear = True

    if st.button("Generate", type="primary"):
        if not banks:
            st.error("Select at least one bank.")
        elif clear_output and not confirm_clear:
            st.error("Confirm deletion to proceed, or uncheck 'Clear existing output files first'.")
        else:
            try:
                with st.spinner("Generating..."):
                    paths = adm.generate_data(
                        banks=banks, start=start, days=int(days), fmt=fmt,
                        out_dir=output_dir, profiles_dir=profiles_dir,
                        schema_path=schema_path,
                        seed=int(seed_val) if use_seed else None,
                        clear_output=clear_output,
                    )
                _invalidate()
                st.success(f"Wrote {len(paths)} file(s) to '{output_dir}'.")
                with st.expander("Files written"):
                    st.write([p.name for p in paths])
            except (ProfileError, SchemaError, ValueError) as exc:
                st.error(f"Generation failed: {exc}")


# === Tab 2: Analytics config ===============================================
with tab_cfg:
    st.subheader("Rules")
    try:
        rules_doc = adm.read_rules_doc(config_dir)
        rules_list = rules_doc.get("rules", [])
        edited_rules = []
        for i, rule in enumerate(rules_list):
            with st.container(border=True):
                st.markdown(f"**{rule.get('id', f'rule {i}')}** — `{rule.get('metric','')}` "
                            f"`{rule.get('op','')}`")
                cols = st.columns([2, 1, 1])
                thr = rule.get("threshold")
                new_rule = dict(rule)
                if isinstance(thr, (list, tuple)) and len(thr) == 2:
                    low = cols[0].number_input("low", value=float(thr[0]), key=f"lo_{i}")
                    high = cols[0].number_input("high", value=float(thr[1]), key=f"hi_{i}")
                    new_rule["threshold"] = [low, high]
                else:
                    try:
                        tv = float(thr)
                    except (TypeError, ValueError):
                        tv = 0.0
                    new_rule["threshold"] = cols[0].number_input(
                        "threshold", value=tv, key=f"thr_{i}")
                sev = rule.get("severity", "info")
                new_rule["severity"] = cols[1].selectbox(
                    "severity", SEVERITIES,
                    index=SEVERITIES.index(sev) if sev in SEVERITIES else 0,
                    key=f"sev_{i}")
                new_rule["enabled"] = cols[2].checkbox(
                    "enabled", value=rule.get("enabled", True), key=f"en_{i}")
                edited_rules.append(new_rule)

        use_raw_rules = False
        with st.expander("Raw JSON (advanced)"):
            raw_rules_text = st.text_area(
                "rules.json", value=json.dumps(rules_doc, indent=2), height=300,
                key="raw_rules")
            use_raw_rules = st.checkbox("Use raw JSON on save", key="use_raw_rules")

        if st.button("Save rules", type="primary"):
            try:
                if use_raw_rules:
                    doc = json.loads(raw_rules_text)
                else:
                    doc = dict(rules_doc)
                    doc["rules"] = edited_rules
                adm.save_rules_doc(config_dir, doc)
                _invalidate()
                st.success("Saved rules.json (previous version backed up).")
            except (ConfigError, json.JSONDecodeError) as exc:
                st.error(f"Could not save rules: {exc}")
    except ConfigError as exc:
        st.error(f"Could not read rules: {exc}")

    st.divider()
    st.subheader("Factors")
    try:
        factors = adm.read_factors(config_dir)
        new_factors = json.loads(json.dumps(factors))  # deep copy

        hqla = new_factors.get("hqla", {}).get("haircut_by_level")
        if isinstance(hqla, dict):
            st.markdown("**HQLA haircuts** (0–1)")
            hc = st.columns(len(hqla))
            for j, (level, val) in enumerate(list(hqla.items())):
                hqla[level] = hc[j].number_input(
                    level, min_value=0.0, max_value=1.0, value=float(val),
                    step=0.01, key=f"hc_{level}")

        inflow = new_factors.get("inflow_rate", {})
        if "inflow_cap_pct_of_outflows" in inflow:
            inflow["inflow_cap_pct_of_outflows"] = st.number_input(
                "Inflow cap (% of outflows, 0–1)", min_value=0.0, max_value=1.0,
                value=float(inflow["inflow_cap_pct_of_outflows"]), step=0.05,
                key="inflow_cap")

        anomaly = new_factors.get("analytics", {}).get("anomaly", {})
        if anomaly:
            st.markdown("**Anomaly thresholds**")
            ac = st.columns(3)
            for j, key in enumerate(("zscore_threshold", "iqr_multiplier", "day_over_day_pct_jump")):
                if key in anomaly:
                    anomaly[key] = ac[j].number_input(
                        key, value=float(anomaly[key]), step=0.1, key=f"an_{key}")

        use_raw_factors = False
        with st.expander("Raw JSON (advanced)"):
            raw_factors_text = st.text_area(
                "factors.json", value=json.dumps(new_factors, indent=2), height=300,
                key="raw_factors")
            use_raw_factors = st.checkbox("Use raw JSON on save", key="use_raw_factors")

        if st.button("Save factors", type="primary"):
            try:
                to_save = json.loads(raw_factors_text) if use_raw_factors else new_factors
                adm.save_factors(config_dir, to_save)
                _invalidate()
                st.success("Saved factors.json (previous version backed up).")
            except (ConfigError, json.JSONDecodeError) as exc:
                st.error(f"Could not save factors: {exc}")
    except ConfigError as exc:
        st.error(f"Could not read factors: {exc}")


# === Tab 3: Bank profiles ==================================================
with tab_prof:
    st.subheader("Edit bank profile")
    try:
        schema = _load_schema_cached(schema_path)
    except SchemaError as exc:
        st.error(f"Could not load schema: {exc}")
        schema = None

    profiles = adm.list_profiles(profiles_dir)
    if not profiles:
        st.warning(f"No profiles found in '{profiles_dir}'.")
    elif schema is not None:
        bank = st.selectbox("Profile", profiles)
        try:
            raw = adm.read_profile_raw(profiles_dir, bank)
        except ProfileError as exc:
            st.error(f"Could not read profile: {exc}")
            raw = None

        if raw is not None:
            description = st.text_input("Description", value=str(raw.get("description", "")))

            st.markdown("**Table weights** (prefix → weight)")
            table_weights = _dist_editor("table_weights", raw.get("table_weights", {}))
            st.markdown("**Product weights** (product id → weight)")
            product_weights = _dist_editor("product_weights", raw.get("product_weights", {}))
            st.markdown("**Amount scale** (prefix → multiplier)")
            amount_scale = _dist_editor("amount_scale", raw.get("amount_scale", {}))

            st.caption("Counterparty and collateral distributions are editable via the raw JSON below.")

            assembled = {
                "bank": bank,
                "description": description,
                "table_weights": table_weights,
                "product_weights": product_weights,
                "amount_scale": amount_scale,
                "counterparty_distribution": raw.get("counterparty_distribution", {}),
                "collateral_distribution": raw.get("collateral_distribution", {}),
            }

            use_raw_profile = False
            with st.expander("Raw JSON (advanced)"):
                raw_profile_text = st.text_area(
                    f"{bank}.json", value=json.dumps(assembled, indent=2), height=320,
                    key="raw_profile")
                use_raw_profile = st.checkbox("Use raw JSON on save", key="use_raw_profile")

            if st.button("Save profile", type="primary"):
                try:
                    to_save = json.loads(raw_profile_text) if use_raw_profile else assembled
                    path, warnings = adm.save_profile(profiles_dir, bank, to_save, schema)
                    _invalidate()
                    for w in warnings:
                        st.warning(w)
                    st.success(f"Saved {path.name} (previous version backed up).")
                except (ProfileError, json.JSONDecodeError) as exc:
                    st.error(f"Could not save profile: {exc}")
