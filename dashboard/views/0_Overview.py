import altair as alt
import pandas as pd
import streamlit as st

from common import (COUNT_AXIS, DOWN, INK_2, UP, chart_block, coverage, live_snapshot, local, page_header, pct)
from db import query

cov = coverage()
live_last = local(cov.live_last)
page_header(
    "What happens to PC games after they come out?",
    "This dashboard follows **54 popular PC games on Steam** — how many people play them, "
    "how their prices change, and what players say about them. Each page answers one question.",
    period=f"monthly players {cov.monthly_first:%b %Y} – {cov.monthly_last:%b %Y} (complete months) · "
           f"live hourly players up to {live_last:%d %b %Y, %H:%M}",
    project_title=True,
)

k = query("""
    select
        (select count(*) from dim_game)                                          as games,
        (select count(*) from dim_game where is_free)                            as free_games,
        (select min(activity_month) from fact_player_activity_monthly)           as first_month,
        (select count(*) from fact_player_activity)                              as readings,
        (select count(*) from fact_price_snapshot)                               as price_changes,
        (select count(distinct shop_id) from fact_price_snapshot)                as shops,
        (select count(*) from fact_reviews)                                      as reviews
""").iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Games followed", f"{k.games}", help=f"{k.free_games} of them are free-to-play.", border=True)
c2.metric("Player history since", f"{k.first_month:%Y}", help="Monthly player numbers go back this far.", border=True)
c3.metric("Player-count readings", f"{k.readings / 1e6:.1f} million", help="Individual snapshots of how many people were playing.", border=True)
c4.metric("Price changes tracked", f"{k.price_changes:,}", help=f"Across {k.shops} online shops, including Steam.", border=True)

# ---- Right now: the live hourly feed ------------------------------------------------------------
snap = live_snapshot()
month = pd.Timestamp(cov.monthly_last)
comparable = snap.dropna(subset=["vs_last_month"])
st.markdown("### Right now")
st.caption(f"From the hourly live feed. Last reading: **{live_last:%a %d %b %Y, %H:%M}** (Berlin time). "
           f"Numbers update each time the pipeline runs. The last 7 days are compared with **{month:%B %Y}**, "
           "the last complete month on the other pages.")

up_row = comparable.loc[comparable["vs_last_month"].idxmax()]
down_row = comparable.loc[comparable["vs_last_month"].idxmin()]
r1, r2, r3 = st.columns(3)
r1.metric("Playing right now, all games", f"{snap['now_players'].sum():,.0f}", border=True,
          help=f"Sum of the latest hourly reading across the {len(snap)} games we follow.")
r2.metric(f"Biggest rise vs. {month:%B}", up_row["name"], f"{pct(up_row['vs_last_month'], signed=True)}", border=True,
          help=f"Average of the last 7 days compared with the {month:%B %Y} monthly average.")
r3.metric(f"Biggest fall vs. {month:%B}", down_row["name"], f"{pct(down_row['vs_last_month'], signed=True)}", border=True,
          help=f"Average of the last 7 days compared with the {month:%B %Y} monthly average.")

movers = pd.concat([comparable.nlargest(6, "vs_last_month"), comparable.nsmallest(6, "vs_last_month")]).drop_duplicates("steam_app_id")
movers["direction"] = movers["vs_last_month"].map(lambda v: "Up" if v >= 0 else "Down")
move_bars = alt.Chart(movers).mark_bar(cornerRadiusEnd=4, height=18).encode(
    x=alt.X("vs_last_month:Q", title=f"Last 7 days vs. {month:%B %Y} average (log scale)",
            scale=alt.Scale(type="symlog", constant=0.5), axis=alt.Axis(format="+%", values=[-0.8, -0.5, 0, 0.5, 1, 2, 5, 10])),
    y=alt.Y("name:N", sort="-x", title=None),
    color=alt.Color("direction:N", scale=alt.Scale(domain=["Up", "Down"], range=[UP, DOWN]), legend=None),
    tooltip=[alt.Tooltip("name:N", title="Game"),
             alt.Tooltip("avg_7d:Q", title="Last 7 days, average", format=",.0f"),
             alt.Tooltip("last_month_avg:Q", title=f"{month:%B %Y} average", format=",.0f"),
             alt.Tooltip("vs_last_month:Q", title="Change", format="+.0%"),
             alt.Tooltip("now_players:Q", title="Latest reading", format=",.0f")])
move_labels = move_bars.mark_text(dx=4, align="left", color=INK_2).encode(
    text=alt.Text("vs_last_month:Q", format="+.0%"), color=alt.value(INK_2))
move_labels_neg = move_bars.mark_text(dx=-4, align="right", color=INK_2).encode(
    text=alt.Text("vs_last_month:Q", format="+.0%"), color=alt.value(INK_2))
chart_block(
    f"{up_row['name']} is the big mover this week: {pct(up_row['vs_last_month'], signed=True)} "
    f"on its {month:%B} average",
    f"The 6 biggest rises and 6 biggest falls. Each bar compares a game's average players over the last 7 days "
    f"with its {month:%B %Y} monthly average. The scale is compressed so a +800% jump and a −50% dip both fit.",
    alt.layer(move_bars,
              move_labels.transform_filter("datum.vs_last_month >= 0"),
              move_labels_neg.transform_filter("datum.vs_last_month < 0")).properties(height=320),
    "The monthly pages stop at the last complete month, so big updates this month only show up here. "
    "A jump like this usually means a major update, a new season or a launch on a new platform.",
)

with st.expander("All games right now"):
    st.dataframe(
        snap.sort_values("now_players", ascending=False)[
            ["name", "now_players", "peak_24h", "avg_7d", "last_month_avg", "vs_last_month"]],
        hide_index=True,
        column_config={
            "name": "Game",
            "now_players": st.column_config.NumberColumn("Latest reading", format="localized"),
            "peak_24h": st.column_config.NumberColumn("Peak, last 24 hours", format="localized"),
            "avg_7d": st.column_config.NumberColumn("Average, last 7 days", format="localized"),
            "last_month_avg": st.column_config.NumberColumn(f"Average, {month:%b %Y}", format="localized"),
            "vs_last_month": st.column_config.NumberColumn(f"7 days vs. {month:%b %Y}", format="percent"),
        },
    )
    st.caption("Empty comparison = the game has no complete month yet.")

genres = query("""
    select trim(g) as genre, count(*) as games
    from dim_game, unnest(string_split(steam_genres, ',')) as t(g)
    where steam_genres is not null
    group by 1
    order by 2 desc
""")
top = genres.head(10)
lead = top.iloc[0]

bars = alt.Chart(top).mark_bar(color=INK_2, cornerRadiusEnd=4, height=18).encode(
    x=alt.X("games:Q", title="Number of games", axis=COUNT_AXIS),
    y=alt.Y("genre:N", sort="-x", title=None),
    tooltip=[alt.Tooltip("genre:N", title="Genre"), alt.Tooltip("games:Q", title="Games")],
)
labels = bars.mark_text(align="left", dx=4, color=INK_2).encode(text="games:Q")
chart_block(
    f"{lead.genre} games make up the biggest share: {lead.games} of the {k.games} games we follow",
    "Each bar counts the games that Steam files under that genre. A game can have several genres, "
    "so the bars add up to more than 54.",
    (bars + labels).properties(height=320),
    "The selection leans towards big action and role-playing games, so results describe popular, "
    "mainstream PC games more than small niche titles.",
)

st.markdown("#### Where to go next")
cols = st.columns(3)
guide = [
    ("views/1_Lifecycle.py", "Life after launch", "How many players does a game keep after its launch rush?"),
    ("views/2_Activity_Health.py", "Activity health", "Which games are growing, holding steady, or shrinking right now?"),
    ("views/3_Sale_Effect.py", "Do sales bring players?", "When a game goes on sale, do the extra players stay?"),
    ("views/4_Market_Events.py", "Unusual days", "Which days saw a sudden rush or collapse, and was a sale involved?"),
    ("views/5_Game_Explorer.py", "Game explorer", "Everything we know about one game: players, prices, reviews."),
]
for i, (path, label, blurb) in enumerate(guide):
    with cols[i % 3]:
        with st.container(border=True):
            st.page_link(path, label=f"**{label}**")
            st.caption(blurb)

gap_note = (f"; no readings {local(cov.live_gap_start):%d %b %H:%M} – {local(cov.live_gap_end):%d %b %H:%M} (collector outage)"
            if pd.notna(cov.live_gap_start) else "")
with st.expander("Where the data comes from"):
    st.markdown(f"""
| Data | Source | Covers |
|---|---|---|
| Players online, monthly | SteamCharts (plus a Kaggle archive to fill gaps) | {cov.monthly_first:%b %Y} – {cov.monthly_last:%b %Y} (complete months only), 52 games |
| Players online, every 5 minutes | Historical backfill | {local(cov.fine_first):%b %Y} – {local(cov.fine_last):%b %Y}, 21 games |
| Players online, hourly | Steam API (live pipeline) | {local(cov.live_first):%d %b %Y} – {live_last:%d %b %Y, %H:%M}{gap_note}, all 54 games |
| Prices & discounts | IsThereAnyDeal price history | All shops, 53 games |
| Player reviews | Steam reviews (1,000 most recent per game) | All 54 games |
| Critic reviews | OpenCritic | 12 games |
""")
