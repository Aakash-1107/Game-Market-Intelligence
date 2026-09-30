import altair as alt
import pandas as pd
import streamlit as st

from common import (COUNT_AXIS, DOWN, INK_2, UP, chart_block, coverage, live_snapshot, local, pct, pipeline_counts,
                    project_header)
from db import query

cov = coverage()
live_last = local(cov.live_last)
k = pipeline_counts()
project_header(f"What happens to PC games after they come out? This dashboard follows {k.games} popular PC games on "
               "Steam: how many people play them, how their prices change, and what players say about them.")

# ---- Pipeline scale ----------------------------------------------------------------------------
with st.container(horizontal=True):  # wraps to 2x2 on narrow windows instead of truncating the numbers
    st.metric("Games followed", f"{k.games}", help=f"{k.free_games} of them are free-to-play.", border=True)
    st.metric("Player history since", f"{k.first_month:%Y}", help="Monthly player numbers go back this far.", border=True)
    st.metric("Player-count readings", f"{k.readings / 1e6:.1f} million", help="Individual snapshots of how many people were playing.", border=True)
    st.metric("Price changes tracked", f"{k.price_changes:,}", help=f"Across {k.shops} online shops, including Steam.", border=True)

# ---- Right now: the live hourly feed ------------------------------------------------------------
snap = live_snapshot()
month = pd.Timestamp(cov.monthly_last)
comparable = snap.dropna(subset=["vs_last_month"])
up_row = comparable.loc[comparable["vs_last_month"].idxmax()]
down_row = comparable.loc[comparable["vs_last_month"].idxmin()]
vs_help = f"Average of the last 7 days compared with the {month:%B %Y} monthly average."
c1, c2, c3 = st.columns(3)  # columns (not a horizontal container) so the three cards share one height
with c1:
    st.metric(f"Latest reading: {live_last:%a %d %b, %H:%M}", f"{snap['now_players'].sum():,.0f}", border=True,
              height="stretch",
              help=f"Players online, summed over the latest hourly reading of the {len(snap)} games we follow "
                   f"({live_last:%a %d %b %Y, %H:%M}, Berlin time). Updated whenever the warehouse is rebuilt; "
                   "hourly readings are collected continuously.")
with c2:
    st.metric(f"Biggest mover vs. {month:%B}", up_row["name"], f"{pct(up_row['vs_last_month'], signed=True)}",
              border=True, height="stretch", help=vs_help)
with c3:
    st.metric(f"Biggest drop vs. {month:%B}", down_row["name"], f"{pct(down_row['vs_last_month'], signed=True)}",
              border=True, height="stretch", help=vs_help)

N_MOVERS = 6  # rises and falls shown each
movers = pd.concat([comparable.nlargest(N_MOVERS, "vs_last_month"), comparable.nsmallest(N_MOVERS, "vs_last_month")]).drop_duplicates("steam_app_id")
movers["direction"] = movers["vs_last_month"].map(lambda v: "Up" if v >= 0 else "Down")
# Explicit order: Vega-Lite drops sort="-x" when bars and labels are layered (the bars came out alphabetical)
mover_order = movers.sort_values("vs_last_month", ascending=False)["name"].tolist()
move_bars = alt.Chart(movers).mark_bar(cornerRadiusEnd=4, height=18).encode(
    x=alt.X("vs_last_month:Q", title=f"Last 7 days vs. {month:%B %Y} average (compressed scale)",
            scale=alt.Scale(type="symlog", constant=0.5, padding=36),  # padding: room for the end labels
            axis=alt.Axis(format="+%", values=[-0.8, -0.5, 0, 0.5, 1, 2, 5, 10])),
    y=alt.Y("name:N", sort=mover_order, title=None),
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
    "Which games gained or lost the most players this week?",
    f"The {N_MOVERS} biggest rises and falls: each game's last 7 days compared with **its own {month:%B %Y} "
    "average** (0% = no change).",
    alt.layer(move_bars,
              move_labels.transform_filter("datum.vs_last_month >= 0"),
              move_labels_neg.transform_filter("datum.vs_last_month < 0")).properties(height=300),
    "The monthly pages stop at the last complete month, so big updates this month only show up here. "
    "A jump like this usually means a major update, a new season or a launch on a new platform.",
    how_label=None,
    details=(f"Out of the {len(comparable)} games with both numbers; one bar per game. The scale is compressed so a "
             "+800% jump and a −50% dip both fit."),
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
    from marts.dim_game, unnest(string_split(steam_genres, ',')) as t(g)
    where steam_genres is not null
    group by 1
    order by 2 desc
""")
top = genres.head(10)
lead = top.iloc[0]

bars = alt.Chart(top).mark_bar(color=INK_2, cornerRadiusEnd=4, height=18).encode(
    x=alt.X("games:Q", title="Number of games", axis=COUNT_AXIS),
    y=alt.Y("genre:N", sort=top["genre"].tolist(), title=None),  # explicit order, see mover_order
    tooltip=[alt.Tooltip("genre:N", title="Genre"), alt.Tooltip("games:Q", title="Games")],
)
labels = bars.mark_text(align="left", dx=4, color=INK_2).encode(text="games:Q")
chart_block(
    f"{lead.genre} games make up the biggest share: {lead.games} of the {k.games} games we follow",
    "Each bar counts the games that Steam files under that genre. A game can have several genres, "
    f"so the bars add up to more than {k.games}.",
    (bars + labels).properties(height=320),
    "The selection leans towards big action and role-playing games, so results describe popular, "
    "mainstream PC games more than small niche titles.",
)

st.markdown("#### Where to go next")
guide = [
    ("views/1_Lifecycle.py", "Life after launch", "How many players does a game keep after its launch rush?"),
    ("views/2_Activity_Health.py", "Activity health", "Which games are growing, holding steady, or shrinking right now?"),
    ("views/3_Sale_Effect.py", "Do discounts bring players?", "When a game is discounted, do the extra players stay?"),
    ("views/4_Market_Events.py", "Unusual days", "Which days saw a sudden rush or collapse, and was a discount involved?"),
    ("views/5_Game_Explorer.py", "Game explorer", "Everything we know about one game: players, prices, reviews."),
    ("views/6_Data.py", "How the data is built", "Where the numbers come from, how fresh they are, and what's missing."),
]
# One st.columns row per 3 cards + height="stretch": every card in a row gets the height of the tallest one
for start in range(0, len(guide), 3):
    for col, (path, label, blurb) in zip(st.columns(3), guide[start:start + 3]):
        with col.container(border=True, height="stretch"):
            st.page_link(path, label=f"**{label}**")
            st.caption(blurb)

st.caption("Data from the Steam Web API. Not affiliated with or endorsed by Valve.")
