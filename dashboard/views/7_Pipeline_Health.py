import altair as alt
import pandas as pd
import streamlit as st

from common import DAY_AXIS, FLAT, chart_block, local, page_header
from db import ops_attached, query, query_live

LABELS = {
    "hourly_player_counts": "Hourly player counts",
    "prices": "Prices (ITAD)",
    "app_details": "Game details (Steam)",
    "reviews": "Player reviews (Steam)",
    "steamcharts_monthly": "Monthly players (SteamCharts)",
    "dbt_build": "Warehouse build (dbt)",
}
BADGE = {"ok": ":green-badge[:material/check_circle: OK]", "warn": ":orange-badge[:material/warning: Warning]",
         "fail": ":red-badge[:material/error: Failing]"}

page_header(
    "Pipeline health",
    "Is the pipeline healthy right now, and if not, where did it fail? Three layers of monitoring feed this page: "
    "Prefect Cloud shows whether a flow ran; the ingestion log records every request per game; these checks turn "
    "both into one status per component, computed at the moment you open the page.",
)

if not ops_attached():
    st.warning("The pipeline logs live in Neon and could not be reached (DATABASE_URL missing or the connection "
               "failed). All other pages work without them.", icon=":material/cloud_off:")
    st.stop()

# ---- Status per component (a view: evaluated now, against the live logs) ------------------------
health = query_live("""
    select component, health_status, last_status, last_success_at, hours_since_last_success, last_error, checked_at
    from observability.mart_pipeline_health
""").set_index("component").reindex(list(LABELS)).reset_index()
checked = local(health["checked_at"].iloc[0])
n_bad = int((health["health_status"] != "ok").sum())
st.markdown(f"#### {'Everything is healthy' if n_bad == 0 else f'{n_bad} of {len(health)} components need attention'}")
st.caption(f"Checked {checked:%a %d %b %Y, %H:%M} (Berlin time). Refreshes every minute.")


def ago(hours: float) -> str:
    if hours < 1:
        return f"{hours * 60:.0f} min ago"
    return f"{hours:.0f} h ago" if hours < 48 else f"{hours / 24:.0f} days ago"


# Thresholds stay in the model (mart_pipeline_health) and docs/PIPELINE.md; the cards show status only.
cols = st.columns(3)
for i, r in health.iterrows():
    with cols[i % 3].container(border=True, height="stretch"):
        st.markdown(f"**{LABELS[r.component]}**  \n{BADGE[r.health_status]}")
        if pd.notna(r.last_success_at):
            st.markdown(f"Last success: {ago(r.hours_since_last_success)} "
                        f"({local(r.last_success_at):%a %d %b, %H:%M})")
        else:
            st.markdown("Last success: never")
        if r.last_status in ("failed", "partial", "skipped"):
            st.caption(f"Latest attempt {r.last_status.replace('_', ' ')}"
                       + (f": {str(r.last_error)[:220]}" if pd.notna(r.last_error) else ""))

st.caption("Not monitored stage by stage: the hourly player-count flow (Prefect managed pool). Its health comes from "
           "the ingestion log (one row per game per hour) and data freshness.  \n"
           "The tables below cover the daily flow only: its stage runs (log entries), games collected per source "
           "(full daily flow runs) and its dbt builds (latest warehouse builds).")

with st.expander("Show log entries"):
    log = query_live("""
        select started_at, flow_name, stage, status, records_in, records_out, error_message
        from observability.mart_pipeline_stage_runs
        order by started_at desc, stage
        limit 30
    """)
    log["started_at"] = log["started_at"].map(lambda t: local(t).tz_localize(None))
    st.dataframe(log, hide_index=True, column_config={
        "started_at": st.column_config.DatetimeColumn("Time (Berlin)", format="ddd D MMM, HH:mm:ss"),
        "flow_name": "Flow", "stage": "Stage", "status": "Status",
        "records_in": st.column_config.NumberColumn("Records in", help="e.g. games attempted"),
        "records_out": st.column_config.NumberColumn("Records out", help="e.g. games succeeded / files written"),
        "error_message": st.column_config.TextColumn("Error", width="large"),
    })
    st.caption("The latest 30 stage runs of the daily flow (pipeline_run_log). The hourly player-count flow logs "
               "per game in the ingestion log instead.")

# ---- Hourly collection: completeness per UTC day -----------------------------------------------------
hourly = query("""
    select activity_date, attempts, failures, succeeded_slots, expected, completeness_pct
    from observability.mart_ingestion_daily
    where component = 'hourly_player_counts'
      and activity_date < cast(current_timestamp at time zone 'UTC' as date)  -- today is still collecting
    order by activity_date
""")
hourly["activity_date"] = pd.to_datetime(hourly["activity_date"])
tip = [alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
       alt.Tooltip("completeness_pct:Q", title="Completeness %", format=".1f"),
       alt.Tooltip("succeeded_slots:Q", title="Game-hours collected"), alt.Tooltip("expected:Q", title="Expected"),
       alt.Tooltip("failures:Q", title="Failed requests")]
line = alt.Chart(hourly).mark_line(point=True, strokeWidth=1.8, color=FLAT).encode(
    x=alt.X("activity_date:T", title=DAY_AXIS, axis=alt.Axis(format="%d %b")),
    y=alt.Y("completeness_pct:Q", title="Completeness", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(format=".0f")),
    tooltip=tip)
worst = hourly.sort_values("completeness_pct").iloc[0] if len(hourly) else None
left, right = st.columns(2, gap="large")
with left:
    chart_block(
        "Hourly collection" if worst is None else
        f"Hourly collection: lowest day {worst.activity_date:%d %b} at {worst.completeness_pct:.0f}%",
        "Each point is one UTC day of the hourly player-count collector. **100% = every active game, every hour.**",
        line.properties(height=260),
        "A dip is a collector outage or rate limiting. The daily sources are not on this chart: they only run when the "
        "daily flow runs (next to it).",
        details=(f"100% is {int(hourly['expected'].iloc[-1]) if len(hourly) else 0} game-hours a day (active games × 24). "
                 "Today is left out until the UTC day is complete. Days without any attempt count as 0%. "
                 "Games added recently make earlier days read slightly below 100%."),
    )

# ---- Daily flow runs: chart (every UTC date on which at least one daily source ran) + table (full flow runs) ----
DAILY = {"prices": "Prices (ITAD)", "app_details": "Game details", "reviews": "Player reviews",
         "steamcharts_monthly": "Monthly players"}
src = query("""
    select component, activity_date, games_succeeded, games_attempted, expected, completeness_pct
    from observability.mart_ingestion_daily
    where component in ('prices', 'app_details', 'reviews', 'steamcharts_monthly') and games_attempted > 0
    order by activity_date
""")
src["source"] = src["component"].map(DAILY)
src["day"] = pd.to_datetime(src["activity_date"]).dt.strftime("%a %d %b")
src["collected"] = [f"{s_} / {a_} games" for s_, a_ in zip(src["games_succeeded"], src["games_attempted"])]
# Legend like Plotly's: click toggles a source off/on, double-click isolates it (double-click it again for all).
# `shown` starts with every source and a click toggles one out or back in, so Vega-Lite's legend fading (entries
# outside a legend selection are faded) marks exactly the hidden sources. A double-click also fires two clicks,
# which toggle the source out and back in, so the two parameters don't interfere.
shown = alt.selection_point(name="shown", fields=["source"], bind="legend", toggle="true", clear=False,
                            value=[{"source": v} for v in DAILY.values()])
isolated = alt.selection_point(name="isolated", fields=["source"], bind=alt.LegendStreamBinding(legend="dblclick"),
                               toggle="true", clear=False)
visible = {"and": [{"param": "shown", "empty": False}, {"param": "isolated"}]}
bars = alt.Chart(src).mark_bar(cornerRadiusEnd=2).encode(
    x=alt.X("day:O", title=DAY_AXIS, sort=src["day"].unique().tolist(), axis=alt.Axis(labelAngle=0)),
    xOffset=alt.XOffset("source:N", sort=list(DAILY.values())),
    y=alt.Y("completeness_pct:Q", title="% of active games collected", scale=alt.Scale(domain=[0, 100]),
            axis=alt.Axis(format=".0f")),
    color=alt.Color("source:N", title=None, sort=list(DAILY.values())),
    opacity={"condition": {"test": visible, "value": 1}, "value": 0.1},
    tooltip=[alt.Tooltip("source:N", title="Source"),
             alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
             alt.Tooltip("collected:N", title="Collected / attempted"),
             alt.Tooltip("completeness_pct:Q", title="% of active games", format=".1f")],
).add_params(shown, isolated)
with right:
    chart_block(
        "Daily flow runs",
        "One group per UTC day on which a daily source ran, one bar per source. **100% = every active game collected.**",
        bars.properties(height=260),  # the chart is fitted to this height, legend included: same as the hourly chart
        "Days without a run have no bars: the daily flow is started by hand, so a missing day is not an outage. "
        "A short bar means some games failed, or only some were fetched.",
        details=(f"100% = {int(src['expected'].iloc[-1]) if len(src) else 0} active games. Days where only one "
                 "source ran are manual runs or reruns of a few games (e.g. reviews for 8 games on 30 Sep). "
                 "Click a source in the legend to hide or show it; double-click to show only that source "
                 "(double-click it again to show all)."),
    )

# the table: days on which the full daily flow ran (all four sources); one-source days are manual runs
st.markdown("##### Full daily flow runs")
d = src[src.groupby("activity_date")["component"].transform("nunique") == len(DAILY)]
if d.empty:
    st.info("The daily flow has not run yet.")
else:
    d = d.assign(cell=d["games_succeeded"].astype(str) + " / " + d["games_attempted"].astype(str))
    t = d.pivot(index="activity_date", columns="component", values="cell")[list(DAILY)].rename(columns=DAILY)
    missing = (d["games_attempted"] - d["games_succeeded"]).groupby(d["activity_date"]).sum()
    t["status"] = missing.map(lambda m: "Success" if m == 0 else f"Partial ({m} game{'s' if m > 1 else ''} missing)")
    t = t.reset_index().sort_values("activity_date", ascending=False)
    st.dataframe(t, hide_index=True, column_config={
        "activity_date": st.column_config.DateColumn("Run date (UTC)", format="ddd D MMM YYYY"),
        "status": "Overall status"})
    st.caption("Games collected / attempted per source that day (all runs of the day together). Only days on which "
               "all four sources ran. Each run's stages are under *Show log entries* above.")

# ---- dbt builds --------------------------------------------------------------------------------------
runs = query_live("""
    select started_at, finished_at, overall_status, models_ok, models_error, tests_pass, tests_warn, tests_fail,
           node_time_s, invocation_id
    from observability.mart_dbt_run_history
    order by finished_at desc
    limit 10
""")
st.markdown("##### Latest warehouse builds (daily flow)")
if runs.empty:
    st.info("No dbt build has been recorded by the daily flow yet. Manual `dbt build` runs are not recorded.")
else:
    for c in ("started_at", "finished_at"):
        runs[c] = runs[c].map(lambda t: local(t).tz_localize(None) if pd.notna(t) else t)
    st.dataframe(runs, hide_index=True, column_config={
        "started_at": st.column_config.DatetimeColumn("Started (Berlin)", format="D MMM, HH:mm"),
        "finished_at": st.column_config.DatetimeColumn("Finished (Berlin)", format="D MMM, HH:mm"),
        "overall_status": "Result", "models_ok": "Models OK", "models_error": "Model errors",
        "tests_pass": "Tests passed", "tests_warn": "Test warnings", "tests_fail": "Tests failed",
        "node_time_s": st.column_config.NumberColumn("Build time (s)", format="%.0f"),
        "invocation_id": "dbt invocation",
    })
