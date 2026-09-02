"""Streamlit dashboard for the FR 2052a liquidity surveillance engine.

Run with:
    streamlit run fr2052a_analytics/app.py

The app runs the analytics pipeline on an input directory of phase-1 output
files and presents: a severity overview, per-entity metric time series (with an
optional experimental forecast overlay), rule findings, statistical anomalies,
peer comparison, and a business-line breakdown.

All data is synthetic and all metrics are documented approximations; the app
shows this disclaimer prominently. Data-shaping logic lives in
:mod:`fr2052a_analytics.ui_data` (Streamlit-free, unit-tested); this module only
handles layout and widgets.
"""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from fr2052a_analytics import ui_data
from fr2052a_analytics.cli import AnalyzeError
from fr2052a_analytics.config import load_severity_definitions
from fr2052a_analytics.loader import discover_entities
from fr2052a_analytics.pipeline import run_pipeline
from fr2052a_analytics.report import DISCLAIMER

DEFAULT_INPUT = "./output"
DEFAULT_CONFIG = "analytics_config"
ALL_ENTITIES = "All entities"


@st.cache_data(show_spinner=True)
def _cached_pipeline(input_dir: str, config_dir: str, forecast_days: int):
    """Cache pipeline runs keyed by inputs so widget changes don't recompute."""
    return run_pipeline(
        Path(input_dir), Path(config_dir), forecast_days=forecast_days
    )


def _severity_badge(sev: str) -> str:
    color = ui_data.SEVERITY_COLORS.get(sev, "#999999")
    return f"<span style='color:{color};font-weight:600'>{sev.upper()}</span>"


def main() -> None:
    st.set_page_config(page_title="FR 2052a Liquidity Surveillance", layout="wide")
    st.title("FR 2052a Liquidity Surveillance")
    st.caption(DISCLAIMER)

    with st.sidebar:
        st.header("Inputs")
        input_dir = st.text_input("Input directory (phase-1 output)", DEFAULT_INPUT)
        config_dir = st.text_input("Config directory", DEFAULT_CONFIG)
        _entities = discover_entities(Path(input_dir))
        focus_options = [ALL_ENTITIES] + _entities
        focus_entity = st.selectbox("Focus entity", focus_options,
                                    help="Pick one institution to analyze, or All entities for an overview.")
        forecast_days = st.slider("Forecast horizon (days, experimental)", 0, 10, 3)
        run_clicked = st.button("Run analysis", type="primary")

    if not run_clicked and "result" not in st.session_state:
        st.info("Set the input directory and click **Run analysis** to begin.")
        return

    if run_clicked:
        try:
            st.session_state["result"] = _cached_pipeline(input_dir, config_dir, forecast_days)
            st.session_state["focus_entity"] = focus_entity
        except AnalyzeError as exc:
            st.error(f"Analysis failed: {exc}")
            return

    result = st.session_state.get("result")
    if result is None:
        return

    # --- Overview ---------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Files", len(result.files))
    c2.metric("Entities", len(result.entities))
    c3.metric("Report days", len(result.dates))
    c4.metric("Findings", len(result.findings))

    st.subheader("Findings by severity")
    sev_frame = ui_data.severity_summary_frame(result)
    _dom, _rng = ui_data.severity_color_scale()
    sev_chart = (
        alt.Chart(sev_frame)
        .mark_bar()
        .encode(
            x=alt.X("severity:N", sort=_dom, title="severity"),
            y=alt.Y("count:Q", title="count"),
            color=alt.Color("severity:N",
                            scale=alt.Scale(domain=_dom, range=_rng),
                            legend=None),
            tooltip=["severity", "count"],
        )
    )
    st.altair_chart(sev_chart, use_container_width=True)

    try:
        _defs = load_severity_definitions(Path(config_dir))
        defs = ui_data.severity_definitions(_defs)
    except Exception:
        defs = ui_data.severity_definitions(None)
    with st.expander("Severity legend"):
        for sev in ui_data.SEVERITY_ORDER:
            st.markdown(
                f"{_severity_badge(sev)} — {defs.get(sev, '')}",
                unsafe_allow_html=True,
            )

    # --- Entity drill-down ------------------------------------------------
    st.subheader("Entity liquidity profile")
    focus = st.session_state.get("focus_entity", ALL_ENTITIES)
    if focus != ALL_ENTITIES and focus in result.entities:
        entity = focus
        st.markdown(
            "Focus entity: "
            f"<span style='font-size:2rem;font-weight:800;color:#00008B'>{entity}</span>",
            unsafe_allow_html=True,
        )
        st.caption("Locked to the focus entity chosen in the sidebar. Change it there and re-run.")
    else:
        entity = st.selectbox("Entity", result.entities)
    metrics = ui_data.available_metrics(result)
    default_metric = "approx_lcr" if "approx_lcr" in metrics else (metrics[0] if metrics else None)
    metric = st.selectbox("Metric", metrics,
                          index=metrics.index(default_metric) if default_metric in metrics else 0)

    if metric:
        chart_df = ui_data.metric_with_forecast(result, entity, metric)
        if not chart_df.empty:
            pivot = chart_df.pivot_table(index="date", columns="series",
                                         values="value", aggfunc="first")
            st.line_chart(pivot)
            if (chart_df["series"] == "forecast (experimental)").any():
                st.caption("Dashed/added series is an EXPERIMENTAL projection, not a prediction.")
        else:
            st.write("No data for this entity/metric.")

    # --- Findings + anomalies --------------------------------------------
    left, right = st.columns(2)
    with left:
        st.subheader(f"Findings — {entity}")
        f = ui_data.findings_for_entity(result, entity)
        if f.empty:
            st.write("No findings for this entity.")
        else:
            st.dataframe(f[["date", "severity", "rule_id", "metric", "value", "message"]],
                         use_container_width=True, hide_index=True)

            st.markdown("**Finding detail**")
            options = list(range(len(f)))

            def _label(i: int) -> str:
                row = f.iloc[i]
                return f"[{row['severity']}] {row['date']} {row['rule_id']}"

            if len(options) == 1:
                sel = 0
            else:
                sel = st.selectbox(
                    "Select a finding", options, format_func=_label,
                    key=f"finding_detail_{entity}",
                )
            row = f.iloc[sel]
            st.markdown(
                f"{row['rule_id']} &nbsp; {_severity_badge(row['severity'])}",
                unsafe_allow_html=True,
            )
            st.write(f"**Description:** {row.get('description', '')}")
            st.write(f"**Why it matters:** {row.get('rationale', '')}")
            st.write(f"**Recommended action:** {row.get('recommended_action', '')}")
            st.caption(
                f"Rule logic: {row['metric']} {row.get('op', '')} {row['threshold']} "
                f"(observed value: {row['value']})"
            )

            g = ui_data.gauge_data(row)
            gauge_df = pd.DataFrame([{"label": "breach", "percent": g["percent"]}])
            base = alt.Chart(gauge_df).encode(
                x=alt.X("percent:Q", scale=alt.Scale(domain=[0, 100]),
                        title="How far past threshold (capped at 100%)"),
                y=alt.Y("label:N", title=None),
            )
            bar = base.mark_bar(color=g["color"])
            st.altair_chart(bar, use_container_width=True)

            try:
                delta = float(row["value"]) - float(row["threshold"])
                st.metric("Observed", row["value"], delta=delta)
            except (TypeError, ValueError):
                st.metric("Observed", row["value"])

            detail_metric = row["metric"]
            trend_df = ui_data.metric_with_forecast(result, entity, detail_metric)
            if not trend_df.empty:
                pivot = trend_df.pivot_table(index="date", columns="series",
                                             values="value", aggfunc="first")
                st.line_chart(pivot)
    with right:
        st.subheader(f"Anomalies — {entity}")
        a = ui_data.anomalies_for_entity(result, entity)
        if a.empty:
            st.write("No anomalies for this entity.")
        else:
            st.dataframe(a[["date", "metric", "method", "value", "reason"]],
                         use_container_width=True, hide_index=True)

    # --- Peer comparison --------------------------------------------------
    st.subheader("Peer comparison")
    if metric:
        peers = ui_data.peers_for_metric(result, metric)
        if peers.empty:
            st.write("Not enough peers on the latest date for comparison.")
        else:
            st.caption(f"Metric '{metric}' on {peers['date'].iloc[0]} — percentile rank within peer group.")
            st.dataframe(
                peers[["entity", "value", "percentile_rank", "peer_median", "peer_q1", "peer_q3"]],
                use_container_width=True, hide_index=True,
            )
            if focus != ALL_ENTITIES:
                st.caption(f"Focus entity '{entity}' is highlighted in its peer group ranking.")

    # --- Business-line breakdown -----------------------------------------
    st.subheader(f"Business-line breakdown — {entity} (latest day)")
    bl = ui_data.business_line_snapshot(result, entity)
    if bl.empty:
        st.write("No business-line data for this entity.")
    else:
        st.dataframe(bl[["BusinessLine", "hqla_stock", "stress_outflows"]],
                     use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
