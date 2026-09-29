import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from common import (DAY_AXIS, DOWN, FLAT, INK, INK_2, LEGEND_HINT, MUTED, STEAM_WIDE, UP, chart_block, coverage,
                    game_image, legend_filter, page_header, sale_bands, utc)
from db import query

cov = coverage()
# games with 5-minute player data = the games this page scores (derived, never hardcoded)
n_games = int(query("select count(distinct steam_app_id) as n from reporting.rpt_market_anomalies").iloc[0]["n"])
page_header(
    "Unusual days: sudden rushes and collapses",
    "Some days, a game's player count jumps or falls far outside its normal range. This page finds those "
    "**unusual days** automatically. It compares each day with the game's previous four weeks and asks: "
    "was there a discount on? Did many games move at once (a Steam-wide cause)? "
    f"Covers the {n_games} games with 5-minute player data.",
    period=f"5-minute player data, {utc(cov.fine_first):%d %b %Y} – {utc(cov.fine_last):%d %b %Y} (UTC days) "
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
           a.is_market_wide, a.games_flagged_same_day, a.during_sale, a.sale_discount_pct, a.anomaly_status,
           a.avg_players, a.baseline_players, a.band_lower_players, a.band_upper_players
    from reporting.rpt_market_anomalies a join marts.dim_game g using (steam_app_id)
""")
an["activity_date"] = pd.to_datetime(an["activity_date"])
flags = an[an["is_anomaly"]].copy()
flags["kind"] = flags.apply(lambda r: STEAM_WIDE if r["is_market_wide"]
                            else ("Unusual surge" if r["direction"] == "spike" else "Unusual drop"), axis=1)
KINDS = ["Unusual surge", "Unusual drop", STEAM_WIDE]
# legend names of the detail chart's series
ACTUAL, BASELINE, NORMAL = "Players online (daily average)", "Baseline (previous 28 days)",     "Expected range (from the previous 28 days)"

# ---- Chart 1: surges and sales -----------------------------------------------------------------
# Only games that were ever on sale, so free-to-play games don't pad the "no sale" group.
paid = an[an["steam_app_id"].isin(an.loc[an["during_sale"], "steam_app_id"].unique()) & (an["anomaly_status"] == "scored")].copy()
paid["bucket"] = pd.cut(paid["sale_discount_pct"].fillna(-1), [-2, 0, 49, 100],
                        labels=["No discount", "Discount, under 50% off", "Discount, 50% off or more"])
paid["surge"] = paid["is_anomaly"] & (paid["direction"] == "spike") & ~paid["is_market_wide"]
rates = paid.groupby("bucket", observed=True).agg(days=("surge", "size"), surges=("surge", "sum")).reset_index()
rates["rate"] = rates["surges"] / rates["days"]
r = rates.set_index("bucket")["rate"]
ratio = r["Discount, 50% off or more"] / r["No discount"]

bars = alt.Chart(rates).mark_bar(cornerRadiusEnd=4, height=26, color=INK_2).encode(
    y=alt.Y("bucket:N", sort=list(rates["bucket"]), title=None),
    x=alt.X("rate:Q", title="Share of days with an unusual surge", axis=alt.Axis(format=".0%", tickCount=4)),
    tooltip=[alt.Tooltip("bucket:N", title=" "), alt.Tooltip("days:Q", title="Days", format=","),
             alt.Tooltip("surges:Q", title="Unusual surges"), alt.Tooltip("rate:Q", title="Share", format=".1%")])
labels = bars.mark_text(align="left", dx=4, color=INK_2).encode(text=alt.Text("rate:Q", format=".1%"))
chart_block(
    f"A sudden rush of players is about {ratio:.0f}× more likely on a day with a big discount than on a normal day",
    "Each bar is the share of days with an unusual surge in players, grouped by how deep the Steam discount was "
    "that day. The ratio in the title is the top bar divided by the no-discount bar.",
    (bars + labels).properties(height=190),
    "Big discounts and sudden player rushes go together. Note that a discount doesn't guarantee a rush, though: "
    "even on 50%+ discount days, most days are ordinary. Publishers also often time discounts to match big updates, "
    "so part of the effect is the update, not the price.",
    details=("An unusual surge = more than 3 standard deviations above the game's own previous 28 days (on a log "
             "scale), and not part of a Steam-wide move. Discount depth = the deepest point of that discount. "
             f"Pooled across {len(paid):,} game-days from the {paid['steam_app_id'].nunique()} games that get "
             "discounted (a game with more days counts more)."),
)

names = sorted(an["name"].unique())

# ---- Chart 2: timeline of unusual days ---------------------------------------------------------
# Fragment: changing the picked games redraws only this chart.
@st.fragment
def timeline_section():
    n_s, n_d = int((flags["kind"] == "Unusual surge").sum()), int((flags["kind"] == "Unusual drop").sum())
    n_w = int(flags.loc[flags["is_market_wide"], "activity_date"].nunique())
    defaults = [g for g in ["Terraria", "Path of Exile", "No Man's Sky", "Counter-Strike 2", "PAYDAY 2"] if g in names]
    picked = st.multiselect("Games on the timeline (up to 5 is easiest to read)", names, default=defaults)
    tl = flags[flags["name"].isin(picked)]
    kind_legend = legend_filter("kind")
    dots = alt.Chart(tl).mark_point(filled=True, size=120, stroke="white", strokeWidth=1.2).encode(
        x=alt.X("activity_date:T", title=DAY_AXIS, axis=alt.Axis(format="%b %Y"),
                scale=alt.Scale(domain=[an["activity_date"].min(), an["activity_date"].max()])),
        y=alt.Y("name:N", title=None, sort=picked),
        shape=alt.Shape("kind:N", title=None, scale=alt.Scale(domain=KINDS, range=["triangle-up", "triangle-down", "circle"])),
        fill=alt.Fill("kind:N", title=None, scale=alt.Scale(domain=KINDS, range=[UP, DOWN, MUTED])),
        tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
                 alt.Tooltip("kind:N", title="What happened"),
                 alt.Tooltip("sale_discount_pct:Q", title="Discount % (if any)")],
        opacity=alt.when(kind_legend).then(alt.value(0.95)).otherwise(alt.value(0.1)),
    ).add_params(kind_legend)
    chart_block(
        f"Unusual days are mostly good news: {n_s} sudden surges against {n_d} drops across all {n_games} games",
        "Each row is a game, each mark an unusual day: up = surge, down = drop. "
        "Grey circles are Steam-wide days, when 3 or more games moved the same way at once.",
        dots.properties(height=max(160, 44 * max(len(picked), 1))),
        "Surges cluster around content updates, new seasons and discounts. Drops are rarer and often come from "
        "server downtime. When a drop hits many games at once, it's Steam itself, not the games.",
        details=(f"{n_w} Steam-wide days in the data. Many games moving at once points to something Steam-wide "
                 "(like an outage or a Steam event), not something about that one game. " + LEGEND_HINT),
    )


timeline_section()

# ---- Chart 3: one game in detail: actual players against the baseline the detector used -----------
# Fragment: picking a game or period redraws only this chart and its table.
@st.fragment
def game_detail_section():
    c1, c2 = st.columns([3, 1])
    with c1:
        game = st.selectbox("Look at one game in detail", names, index=names.index("Terraria") if "Terraria" in names else 0)
    with c2:
        year = st.segmented_control("Period", ["2018", "2019", "2020", "All"], default="2020", required=True,
                                    key="events_year")
    days = an[an["name"] == game].sort_values("activity_date").copy()
    app_id = int(days["steam_app_id"].iloc[0])
    image = days["header_image_url"].iloc[0]
    sales = query("select sale_start, sale_end, max_discount_pct from reporting.rpt_discount_effect where steam_app_id = ?", (app_id,))
    if year != "All":
        days = days[days["activity_date"].dt.year == int(year)]
    days["vs_baseline"] = days["avg_players"] / days["baseline_players"]
    gflags = days[days["is_anomaly"]].copy()
    gflags["kind"] = gflags.apply(lambda r: STEAM_WIDE if r["is_market_wide"]
                                  else ("Unusual surge" if r["direction"] == "spike" else "Unusual drop"), axis=1)
    gflags["known"] = gflags["activity_date"].map(lambda d: known_event(app_id, d))

    left, right = st.columns([1, 4])
    with left:
        game_image(image, width=220)
        st.metric("Unusual days", f"{len(gflags)}")
        st.metric("…of them during a discount", f"{int(gflags['during_sale'].sum())}")
    with right:
        if days.empty:
            st.info("No daily player data for this game in the selected period.")
        else:
            # Headline = the game's own flagged day (Steam-wide days left out) furthest from its 28-day baseline,
            # so title and picture agree
            own = gflags[~gflags["is_market_wide"]]
            if gflags.empty:
                headline = f"{game} had no unusual days in this period"
            elif own.empty:
                wide = gflags["activity_date"].dt.strftime("%d %b %Y").tolist()
                headline = (f"{game} had no unusual days of its own in this period: its only "
                            + ("unusual day was" if len(wide) == 1 else f"{len(wide)} unusual days were")
                            + f" Steam-wide ({', '.join(wide)}), when 3 or more games moved at once")
            else:
                b = own.loc[own["vs_baseline"].map(lambda v: abs(np.log(v))).idxmax()]
                verb = "jumped to" if b.vs_baseline >= 1 else "fell to"
                headline = (f"{game}'s biggest moment: on {b.activity_date:%d %b %Y} players {verb} "
                            f"{b.vs_baseline:.1f}× the level of the previous 28 days" + (f" ({b.known})" if b.known else ""))
            x_dom = [days["activity_date"].min(), days["activity_date"].max()]
            x = alt.X("activity_date:T", title=DAY_AXIS, scale=alt.Scale(domain=x_dom),
                      axis=alt.Axis(format="%b %Y", tickCount="month"))
            # y-axis cut at 1.25x the busiest day: a wide band after a spike would otherwise flatten the line
            y_scale = alt.Scale(domain=[0, days["avg_players"].max() * 1.25], nice=False)
            y = alt.Y("avg_players:Q", title="Players online (daily average)", axis=alt.Axis(format="~s"), scale=y_scale)
            # one row per calendar day: days without complete data become empty rows, so the lines break there
            # instead of joining across the gap
            full = pd.date_range(x_dom[0], x_dom[1], freq="D")
            n_missing = len(full) - days["activity_date"].nunique()
            line_days = (days.set_index("activity_date").reindex(full).rename_axis("activity_date").reset_index())
            tip = [alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
                   alt.Tooltip("avg_players:Q", title="Players online (daily average)", format=",.0f"),
                   alt.Tooltip("baseline_players:Q", title="Previous 28 days (baseline)", format=",.0f"),
                   alt.Tooltip("band_lower_players:Q", title="Expected range from", format=",.0f"),
                   alt.Tooltip("band_upper_players:Q", title="Expected range to", format=",.0f"),
                   alt.Tooltip("z_score:Q", title="Standard deviations from baseline", format="+.1f")]
            # one single-entry legend per series (colour scales resolved independently below), in a row under the
            # chart: together with the day markers and the discount band they don't fit on one row at the top
            def series(name: str, colour: str) -> alt.Color:
                return alt.Color("series:N", title=None, scale=alt.Scale(domain=[name], range=[colour]),
                                 legend=alt.Legend(orient="bottom"))
            band = alt.Chart(line_days.assign(series=NORMAL)).mark_area(opacity=0.18, clip=True).encode(
                x=x, y=alt.Y("band_lower_players:Q", scale=y_scale), y2="band_upper_players:Q", color=series(NORMAL, MUTED))
            base = alt.Chart(line_days.assign(series=BASELINE)).mark_line(strokeDash=[4, 3], strokeWidth=1.2, clip=True).encode(
                x=x, y=alt.Y("baseline_players:Q", scale=y_scale), color=series(BASELINE, MUTED),
                strokeDash=alt.StrokeDash("series:N", title=None, scale=alt.Scale(domain=[BASELINE], range=[[4, 3]]),
                                          legend=alt.Legend(orient="bottom")))
            players = alt.Chart(line_days.assign(series=ACTUAL)).mark_line(strokeWidth=1.6).encode(
                x=x, y=y, tooltip=tip, color=series(ACTUAL, FLAT))
            kinds = ["Unusual surge", "Unusual drop", STEAM_WIDE]
            marks = alt.Chart(gflags).mark_point(filled=True, size=110, opacity=1, stroke="white", strokeWidth=1.5).encode(
                x=x, y="avg_players:Q",
                shape=alt.Shape("kind:N", title=None, scale=alt.Scale(domain=kinds, range=["triangle-up", "triangle-down", "circle"])),
                fill=alt.Fill("kind:N", title=None, scale=alt.Scale(domain=kinds, range=[UP, DOWN, MUTED])),
                tooltip=[alt.Tooltip("kind:N", title="What happened"), *tip,
                         alt.Tooltip("sale_discount_pct:Q", title="Discount % (if any)")])
            layers = [*sale_bands(sales, x_dom), band, base, players, marks]
            notes = gflags[gflags["known"] != ""].drop_duplicates("known")
            if not notes.empty:
                layers.append(alt.Chart(notes).mark_text(align="left", dx=10, dy=-4, fontSize=11, color=INK).encode(
                    x=x, y="avg_players:Q", text="known:N"))
            chart_block(
                headline,
                "The grey band shows what counts as normal on each day. "
                "A day is unusual only if the blue line leaves the band.",
                alt.layer(*layers).resolve_scale(color="independent", strokeDash="independent").properties(height=320),
                "Check each triangle for a yellow band (a discount) or a label (a known update). Surges with neither "
                "usually match news, streamers or events we don't track.",
                details=("Blue line = players online each day (daily average). Dashed line = the baseline the detector "
                         "used: the previous 28 days (their typical level on a log scale); the band (\"Expected "
                         "range\") is ±3 standard deviations around it. Triangles mark unusual days (up = surge, "
                         "down = drop, grey circle = Steam-wide); yellow bands are Steam discounts. The first 3 weeks "
                         "have no band yet (fewer than 21 days of history). The y-axis stops at 1.25× the busiest "
                         "day, so a very wide band can run off the top. "
                         + (f"Gaps in the lines are days without complete data ({n_missing} in this period)."
                            if n_missing else "No days are missing in this period.")),
            )

    if not gflags.empty:
        st.markdown("##### Unusual days for this game")
        tbl = gflags.copy()
        tbl["vs_baseline"] = (tbl["vs_baseline"] * 100).round()
        tbl["sale"] = tbl["sale_discount_pct"].map(lambda d: f"{d:.0f}% off" if pd.notna(d) else "No discount")
        st.dataframe(
            tbl.sort_values("activity_date")[["activity_date", "kind", "avg_players", "baseline_players", "vs_baseline",
                                              "z_score", "sale", "games_flagged_same_day", "known"]],
            hide_index=True,
            column_config={
                "activity_date": st.column_config.DateColumn("Day (UTC)", format="ddd D MMM YYYY"),
                "kind": "What happened",
                "avg_players": st.column_config.NumberColumn("Players online", format="%,.0f"),
                "baseline_players": st.column_config.NumberColumn("Previous 28 days", format="%,.0f"),
                "vs_baseline": st.column_config.NumberColumn("vs. previous 28 days", format="%d%%"),
                "z_score": st.column_config.NumberColumn("Standard deviations", format="%+.1f"),
                "sale": "Steam discount that day",
                "games_flagged_same_day": st.column_config.NumberColumn("Games moving the same way that day"),
                "known": "What we know about this date",
            },
        )


game_detail_section()
