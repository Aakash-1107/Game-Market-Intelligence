import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from common import (DOWN, INK, INK_2, MUTED, STEAM_WIDE, UP, chart_block, coverage, daily_activity, event_chart,
                    game_image, local, page_header)
from db import query

cov = coverage()
page_header(
    "Unusual days: sudden rushes and collapses",
    "Some days, a game's player count jumps or falls far outside its normal range. This page finds those "
    "**unusual days** automatically. It compares each day with the game's previous four weeks and asks: "
    "was there a sale on? Did many games move at once (a Steam-wide cause)? "
    "Covers the 21 games with 5-minute player data.",
    period=f"5-minute player data, {local(cov.fine_first):%d %b %Y} – {local(cov.fine_last):%d %b %Y} "
           "(a historical backfill; unusual days need day-by-day data, which the monthly history doesn't have).",
)

# Real-world events checked against the detector (Task 1 validation). Matched within ±3 days.
KNOWN_EVENTS = [
    (105600, "2020-05-16", "Journey's End, the game's final big update"),
    (238960, "2020-03-13", "New season (\"Delirium\") launched"),
    (238960, "2020-06-19", "New season (\"Harvest\") launched"),
    (275850, "2018-07-24", "\"NEXT\" update added multiplayer"),
    (275850, "2019-08-14", "\"Beyond\" update"),
    (730, "2018-12-06", "Went free-to-play and added a battle-royale mode"),
    (None, "2019-08-14", "Steam-wide drop that evening (likely an outage)"),
]


def known_event(app_id: int, day: pd.Timestamp) -> str:
    for ev_app, ev_day, label in KNOWN_EVENTS:
        if (ev_app is None or ev_app == app_id) and abs((day - pd.Timestamp(ev_day)).days) <= 3:
            return label
    return ""


an = query("""
    select a.steam_app_id, g.name, g.header_image_url, a.activity_date, a.z_score, a.direction, a.is_anomaly,
           a.is_market_wide, a.games_flagged_same_day, a.during_sale, a.sale_discount_pct, a.anomaly_status
    from an_market_anomalies a join dim_game g using (steam_app_id)
""")
an["activity_date"] = pd.to_datetime(an["activity_date"])
flags = an[an["is_anomaly"]].copy()
flags["kind"] = flags.apply(lambda r: STEAM_WIDE if r["is_market_wide"]
                            else ("Unusual surge" if r["direction"] == "spike" else "Unusual drop"), axis=1)
KINDS = ["Unusual surge", "Unusual drop", STEAM_WIDE]

# ---- Chart 1: surges and sales -----------------------------------------------------------------
# Only games that were ever on sale, so free-to-play games don't pad the "no sale" group.
paid = an[an["steam_app_id"].isin(an.loc[an["during_sale"], "steam_app_id"].unique()) & (an["anomaly_status"] == "scored")].copy()
paid["bucket"] = pd.cut(paid["sale_discount_pct"].fillna(-1), [-2, 0, 49, 100],
                        labels=["No sale", "Sale, under 50% off", "Sale, 50% off or more"])
paid["surge"] = paid["is_anomaly"] & (paid["direction"] == "spike") & ~paid["is_market_wide"]
rates = paid.groupby("bucket", observed=True).agg(days=("surge", "size"), surges=("surge", "sum")).reset_index()
rates["rate"] = rates["surges"] / rates["days"]
r = rates.set_index("bucket")["rate"]
ratio = r["Sale, 50% off or more"] / r["No sale"]

bars = alt.Chart(rates).mark_bar(cornerRadiusEnd=4, height=26, color=INK_2).encode(
    y=alt.Y("bucket:N", sort=list(rates["bucket"]), title=None),
    x=alt.X("rate:Q", title="Share of days with an unusual surge", axis=alt.Axis(format=".0%", tickCount=4)),
    tooltip=[alt.Tooltip("bucket:N", title=" "), alt.Tooltip("days:Q", title="Days", format=","),
             alt.Tooltip("surges:Q", title="Unusual surges"), alt.Tooltip("rate:Q", title="Share", format=".1%")])
labels = bars.mark_text(align="left", dx=4, color=INK_2).encode(text=alt.Text("rate:Q", format=".1%"))
chart_block(
    f"A sudden rush of players is about {ratio:.0f}× more likely on a day with a big sale than on a normal day",
    "Each bar is the share of days on which a game had an unusual surge in players. Days are grouped by whether "
    "the game was on sale on Steam that day, and how deep the discount was. "
    f"Only the {paid['steam_app_id'].nunique()} games that go on sale are counted.",
    (bars + labels).properties(height=190),
    "Big discounts and sudden player rushes go together. Note that a sale doesn't guarantee a rush, though: "
    "even on 50%+ sale days, most days are ordinary. Publishers also often time sales to match big updates, "
    "so part of the effect is the update, not the price.",
)

# ---- Chart 2: timeline of unusual days ---------------------------------------------------------
n_s, n_d = int((flags["kind"] == "Unusual surge").sum()), int((flags["kind"] == "Unusual drop").sum())
n_w = int(flags.loc[flags["is_market_wide"], "activity_date"].nunique())
names = sorted(an["name"].unique())
defaults = [g for g in ["Terraria", "Path of Exile", "No Man's Sky", "Counter-Strike 2", "PAYDAY 2"] if g in names]
picked = st.multiselect("Games on the timeline (up to 5 is easiest to read)", names, default=defaults)
tl = flags[flags["name"].isin(picked)]
dots = alt.Chart(tl).mark_point(filled=True, size=120, opacity=0.95, stroke="white", strokeWidth=1.2).encode(
    x=alt.X("activity_date:T", title=None, axis=alt.Axis(format="%b %Y"),
            scale=alt.Scale(domain=[an["activity_date"].min(), an["activity_date"].max()])),
    y=alt.Y("name:N", title=None, sort=picked),
    shape=alt.Shape("kind:N", title=None, scale=alt.Scale(domain=KINDS, range=["triangle-up", "triangle-down", "circle"])),
    fill=alt.Fill("kind:N", title=None, scale=alt.Scale(domain=KINDS, range=[UP, DOWN, MUTED])),
    tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("activity_date:T", title="Day", format="%a %d %b %Y"),
             alt.Tooltip("kind:N", title="What happened"),
             alt.Tooltip("sale_discount_pct:Q", title="Sale discount % (if any)")])
chart_block(
    f"Unusual days are mostly good news: {n_s} sudden surges against {n_d} drops across all 21 games",
    "Each row is a game, each mark an unusual day. Up-triangles are surges, down-triangles are drops. "
    f"Grey circles are days when 3 or more games moved the same way at once ({n_w} such days). That points to "
    "something Steam-wide (like an outage or a Steam event), not something about that one game.",
    dots.properties(height=max(160, 44 * max(len(picked), 1))),
    "Surges cluster around content updates, new seasons and sales. Drops are rarer and often come from "
    "server downtime. When a drop hits many games at once, it's Steam itself, not the games.",
)

# ---- Chart 3: one game in detail (reuses the event-shading pattern) ----------------------------
c1, c2 = st.columns([3, 1])
with c1:
    game = st.selectbox("Look at one game in detail", names, index=names.index("Terraria") if "Terraria" in names else 0)
with c2:
    year = st.segmented_control("Period", ["2018", "2019", "2020", "All"], default="2020", required=True,
                                key="events_year")
row = an[an["name"] == game].iloc[0]
app_id = int(row.steam_app_id)
daily = daily_activity(app_id)
sales = query("select sale_start, sale_end, max_discount_pct from an_sale_effect where steam_app_id = ?", (app_id,))
gflags = flags[flags["steam_app_id"] == app_id].copy()
if year != "All":
    daily = daily[daily["day"].dt.year == int(year)]
    gflags = gflags[gflags["activity_date"].dt.year == int(year)]
gflags["known"] = gflags["activity_date"].map(lambda d: known_event(app_id, d))

left, right = st.columns([1, 4])
with left:
    game_image(row.header_image_url, width=220)
    st.metric("Unusual days", f"{len(gflags)}")
    st.metric("…of them during a sale", f"{int(gflags['during_sale'].sum())}")
with right:
    if daily.empty:
        st.info("No daily player data for this game in the selected period.")
    else:
        # Headline = the flagged day that stands out most on the chart (furthest from 100%), so title and picture agree
        shown = gflags.merge(daily[["day", "vs_typical"]], left_on="activity_date", right_on="day")
        if shown.empty:
            headline = f"{game} had no unusual days in this period"
        else:
            b = shown.loc[shown["vs_typical"].map(lambda v: abs(np.log(v))).idxmax()]
            verb = "jumped to" if b.vs_typical >= 1 else "fell to"
            headline = (f"{game}'s biggest moment: on {b.activity_date:%d %b %Y} players {verb} "
                        f"{b.vs_typical:.1f}× the usual level" + (f" ({b.known})" if b.known else ""))
        chart = event_chart(daily, sales, gflags)
        notes = gflags[gflags["known"] != ""].drop_duplicates("known").merge(
            daily, left_on="activity_date", right_on="day")
        if not notes.empty:
            chart = alt.layer(chart, alt.Chart(notes).mark_text(align="left", dx=10, dy=-4, fontSize=11, color=INK).encode(
                x="day:T", y="vs_typical:Q", text="known:N"))
        chart_block(
            headline,
            "The blue line is players online each day compared with the game's typical level (100%). "
            "Triangles mark unusual days (up = surge, down = drop). Yellow bands are Steam sales.",
            chart,
            "Check each triangle for a yellow band (a sale) or a label (a known update). Surges with neither "
            "usually match news, streamers or events we don't track.",
        )

if not gflags.empty:
    st.markdown("##### Unusual days for this game")
    tbl = gflags.merge(daily[["day", "vs_typical"]], left_on="activity_date", right_on="day", how="left")
    tbl["vs_typical"] = (tbl["vs_typical"] * 100).round()
    tbl["sale"] = tbl["sale_discount_pct"].map(lambda d: f"{d:.0f}% off" if pd.notna(d) else "No sale")
    st.dataframe(
        tbl.sort_values("activity_date")[["activity_date", "kind", "vs_typical", "sale",
                                          "games_flagged_same_day", "known"]],
        hide_index=True,
        column_config={
            "activity_date": st.column_config.DateColumn("Day", format="ddd D MMM YYYY"),
            "kind": "What happened",
            "vs_typical": st.column_config.NumberColumn("vs. typical level", format="%d%%"),
            "sale": "Steam sale that day",
            "games_flagged_same_day": st.column_config.NumberColumn("Games moving the same way that day"),
            "known": "What we know about this date",
        },
    )
