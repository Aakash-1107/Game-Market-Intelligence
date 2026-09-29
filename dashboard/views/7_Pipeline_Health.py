import altair as alt
import pandas as pd
import streamlit as st

from common import DAY_AXIS, chart_block, local, page_header
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
    select component, health_status, last_status, last_success_at, last_attempt_at, hours_since_last_success,
           expected_interval_hours, ok_hours, warn_hours, last_error, latest_data_in_warehouse_at, checked_at
    from observability.mart_pipeline_health
""").set_index("component").reindex(list(LABELS)).reset_index()
checked = local(health["checked_at"].iloc[0])
n_bad = int((health["health_status"] != "ok").sum())
st.markdown(f"#### {'Everything is healthy' if n_bad == 0 else f'{n_bad} of {len(health)} components need attention'}")
st.caption(f"Checked {checked:%a %d %b %Y, %H:%M} (Berlin time). Refreshes every minute.")

cols = st.columns(3)
for i, r in health.iterrows():
    with cols[i % 3].container(border=True, height="stretch"):
        st.markdown(f"**{LABELS[r.component]}**  \n{BADGE[r.health_status]}")
        if pd.notna(r.last_success_at):
            st.markdown(f"Last success {r.hours_since_last_success:,.1f} h ago  \n"
                        f":gray[{local(r.last_success_at):%a %d %b, %H:%M} · expected every "
                        f"{'hour' if r.expected_interval_hours == 1 else f'{r.expected_interval_hours:.0f} h'} · "
                        f"ok ≤ {r.ok_hours:.0f} h, failing > {r.warn_hours:.0f} h]")
        else:
            st.markdown("Never succeeded yet")
        st.markdown(f":gray[Latest attempt: {r.last_status.replace('_', ' ')}]")
        if pd.notna(r.last_error) and r.last_status != "success":
            st.caption(f"Error: {str(r.last_error)[:220]}")

# ---- Completeness per day --------------------------------------------------------------------------
daily = query("""
    select component, activity_date, attempts, successes, failures, succeeded_slots, expected, completeness_pct
    from observability.mart_ingestion_daily
    order by component, activity_date
""")
daily["source"] = daily["component"].map(LABELS)
daily["activity_date"] = pd.to_datetime(daily["activity_date"])
order = [LABELS[c] for c in LABELS if c in set(daily["component"])]
hourly = daily[daily["component"] == "hourly_player_counts"]
x = alt.X("activity_date:T", title=DAY_AXIS, axis=alt.Axis(format="%d %b"))
y = alt.Y("completeness_pct:Q", title="Completeness", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(format=".0f"))
tip = [alt.Tooltip("source:N", title="Source"), alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
       alt.Tooltip("completeness_pct:Q", title="Completeness %", format=".1f"),
       alt.Tooltip("succeeded_slots:Q", title="Succeeded"), alt.Tooltip("expected:Q", title="Expected"),
       alt.Tooltip("failures:Q", title="Failed requests")]
lines = alt.Chart(daily).mark_line(point=True, strokeWidth=1.8).encode(
    x=x, y=y, color=alt.Color("source:N", title=None, sort=order), tooltip=tip)
worst = hourly.sort_values("completeness_pct").iloc[0] if len(hourly) else None
chart_block(
    "How complete was each day's data collection?" if worst is None else
    f"Hourly collection: lowest day {worst.activity_date:%d %b} at {worst.completeness_pct:.0f}%",
    "Each point is one source on one UTC day. **100% = every active game collected**: for hourly player counts "
    f"that is {int(hourly['expected'].iloc[-1]) if len(hourly) else 0} game-hours a day (active games × 24); for the "
    "daily sources, every active game once. Days without any attempt count as 0% (for the daily sources that "
    "means the daily flow did not run that day). Games added recently make earlier days read slightly below 100%.",
    lines.properties(height=320),
    "A dip in the hourly line is a collector outage or rate limiting; a daily source at 0% means the daily flow "
    "was not run that day.",
)

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
st.caption("Not monitored stage by stage: the hourly player-count flow (Prefect managed pool). Its health comes from "
           "the ingestion log (one row per game per hour) and data freshness.")
