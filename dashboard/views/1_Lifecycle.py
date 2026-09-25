import altair as alt
import pandas as pd
import streamlit as st

from common import (COUNT_AXIS, INK, INK_2, MUTED, PATTERN, PATTERN_ORDER, chart_block, coverage, page_header, pct,
                    scale_for, spread_labels)
from db import query

cov = coverage()
last = pd.Timestamp(cov.monthly_last)
LATEST = f"{last:%b %Y}"
page_header(
    "Life after launch",
    "Most games are busiest right after they come out. This page asks **how many of those launch "
    "players a game still has months and years later**. Every game is measured against its own "
    "launch peak (its busiest month in the first four months on Steam), so a blockbuster and a "
    "small game can be compared fairly.",
    period=f"monthly players {cov.monthly_first:%b %Y} – {last:%b %Y} (complete months only). "
           f"\"Latest\" on this page means {last:%B %Y}; newer activity is on the Market overview under *Right now*.",
)

games = query("""
    select steam_app_id, name, lifecycle_status, lifecycle_pattern, release_month,
           retention_m6, retention_m12, retention_m24, latest_vs_launch_peak,
           lowest_vs_launch_peak, has_recovery, first_recovery_month_index
    from an_game_lifecycle
""")
games["pattern"] = games["lifecycle_pattern"].map(lambda p: PATTERN.get(p, (None,))[0])

curves = query("""
    select l.name, l.lifecycle_pattern,
           date_diff('month', l.release_month, m.activity_month) as month_idx,
           m.avg_players / l.launch_peak_avg                     as vs_peak
    from an_game_lifecycle l
    join fact_player_activity_monthly m on m.steam_app_id = l.steam_app_id
    where l.lifecycle_status = 'launch_observed'
      and date_diff('month', l.release_month, m.activity_month) between 0 and 24
""")
curves["pattern"] = curves["lifecycle_pattern"].map(lambda p: PATTERN[p][0])

# "Typical game" = median across games with at least a year of history (a stable comparison set).
settled = curves[curves["lifecycle_pattern"] != "insufficient_history"]
median_curve = settled.groupby("month_idx").agg(vs_peak=("vs_peak", "median"), games=("name", "nunique")).reset_index()
mc = median_curve.set_index("month_idx")["vs_peak"]
m3 = mc.loc[3]
plateau = mc.loc[4:18].median()  # months 4-18: after the launch drop, before the 2-year mark

# ---- Chart 1: the typical curve + a few picked games ------------------------------------------
default = [g for g in ["ELDEN RING", "Baldur's Gate 3", "Subnautica", "Factorio", "Rust"] if g in set(settled["name"])]
picked = st.multiselect("Compare games against the typical curve (up to 5 is easiest to read)",
                        sorted(curves["name"].unique()), default=default)
sel = curves[curves["name"].isin(picked)]

x = alt.X("month_idx:Q", title="Months since the game came out on Steam", scale=alt.Scale(domain=[0, 24]),
          axis=alt.Axis(values=list(range(0, 25, 3))))
y = alt.Y("vs_peak:Q", title="Players, as % of the launch peak", axis=alt.Axis(format="%"))
ref = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=MUTED).encode(y="y:Q")
typical = alt.Chart(median_curve).mark_line(color=INK, strokeWidth=3.5).encode(
    x=x, y=y, tooltip=[alt.Tooltip("month_idx:Q", title="Month"),
                       alt.Tooltip("vs_peak:Q", title="Typical game", format=".0%"),
                       alt.Tooltip("games:Q", title="Games in this month")])

lines = alt.Chart(sel).mark_line(strokeWidth=2, opacity=0.9).encode(
    x=x, y=y, detail="name:N",
    color=alt.Color("pattern:N", title="Pattern after one year", scale=scale_for(PATTERN, PATTERN_ORDER)),
    tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("month_idx:Q", title="Month"),
             alt.Tooltip("vs_peak:Q", title="% of launch peak", format=".0%"),
             alt.Tooltip("pattern:N", title="Pattern")])
ends = sel.loc[sel.groupby("name")["month_idx"].idxmax(), ["name", "month_idx", "vs_peak"]]
ends = pd.concat([ends, median_curve.loc[median_curve["month_idx"] == 24, ["month_idx", "vs_peak"]].assign(name="Typical game")])
y_top = max(1.0, sel["vs_peak"].max() if not sel.empty else 1.0, median_curve["vs_peak"].max())
ends = spread_labels(ends, "vs_peak", min_gap=y_top * 0.055)
ends["weight"] = ends["name"].eq("Typical game").map({True: "bold", False: "normal"})
end_labels = alt.Chart(ends).mark_text(align="left", dx=6, fontSize=11).encode(
    x=x, y=alt.Y("label_y:Q"), text="name:N",
    color=alt.condition("datum.name == 'Typical game'", alt.value(INK), alt.value(INK_2)))

chart_block(
    f"A typical game is down to {pct(m3)} of its launch crowd after 3 months, "
    f"then levels off at around {pct(plateau)}",
    "The thick black line is the typical game (the middle value across "
    f"{settled['name'].nunique()} games). The top grey line at 100% is each game's launch peak. "
    "The thin lines are the games you picked, coloured by the pattern they end up in.",
    (ref + lines + typical + end_labels).properties(height=420),
    "The launch rush is short. Most players who show up in the first weeks are gone within a few months. "
    "After that the curve flattens: the players who are left tend to stay. The small bumps at 12 and 24 months "
    "line up with the game's anniversary, when many games run sales or release updates.",
)

# ---- Chart 2: how many games end up in each pattern -------------------------------------------
counts = (games.dropna(subset=["pattern"]).groupby("pattern").size()
          .reindex(PATTERN_ORDER).fillna(0).astype(int).reset_index(name="games"))
judged = counts[counts["pattern"] != "Too new to tell"]
biggest = judged.sort_values("games", ascending=False).iloc[0]
fast = int(counts.set_index("pattern").loc["Big launch, fast drop", "games"])
grow = int(counts.set_index("pattern").loc["Keeps growing", "games"])

bars = alt.Chart(counts).mark_bar(cornerRadiusEnd=4, height=22).encode(
    y=alt.Y("pattern:N", sort=PATTERN_ORDER, title=None),
    x=alt.X("games:Q", title="Number of games", axis=COUNT_AXIS),
    color=alt.Color("pattern:N", scale=scale_for(PATTERN, PATTERN_ORDER), legend=None),
    tooltip=[alt.Tooltip("pattern:N", title="Pattern"), alt.Tooltip("games:Q", title="Games")])
bar_labels = bars.mark_text(align="left", dx=4, color=INK_2).encode(text="games:Q", color=alt.value(INK_2))
chart_block(
    f"{fast} of {judged['games'].sum()} games had a big launch and then a fast drop — "
    f"but {grow} kept growing past their launch",
    "Each bar counts games by where they stood one year after launch, compared with their launch peak: "
    "**fast drop** = below 30%, **slow fade** = 30–60%, **holds steady** = 60–100%, "
    "**keeps growing** = above 100%. \"Too new to tell\" games haven't been out for a year yet.",
    (bars + bar_labels).properties(height=230),
    "There are two very different kinds of game. Story-driven blockbusters (played once, then finished) "
    "tend to drop fast. Online and multiplayer games that keep adding content often end up bigger than at launch.",
)

# ---- Chart 3: comebacks ------------------------------------------------------------------------
comeback = games[games["has_recovery"] == True].copy()  # noqa: E712 (nullable boolean)
comeback = comeback.sort_values("latest_vs_launch_peak")
cb = comeback.melt(id_vars=["name", "pattern"], value_vars=["lowest_vs_launch_peak", "latest_vs_launch_peak"],
                   var_name="point", value_name="vs_peak")
cb["point"] = cb["point"].map({"lowest_vs_launch_peak": "Lowest point after launch",
                               "latest_vs_launch_peak": LATEST})
order = comeback["name"].tolist()
cy = alt.Y("name:N", sort=order, title=None)
cx = alt.X("vs_peak:Q", title="Players, as % of the launch peak", axis=alt.Axis(format="%"))
rules = alt.Chart(comeback).mark_rule(color=MUTED, strokeWidth=2).encode(
    y=cy, x="lowest_vs_launch_peak:Q", x2="latest_vs_launch_peak:Q")
dots = alt.Chart(cb).mark_point(filled=True, size=110, stroke="white", strokeWidth=1.5, opacity=1).encode(
    y=cy, x=cx,
    fill=alt.Fill("point:N", title=None, scale=alt.Scale(domain=["Lowest point after launch", LATEST],
                                                          range=[MUTED, INK])),
    shape=alt.Shape("point:N", title=None, scale=alt.Scale(domain=["Lowest point after launch", LATEST],
                                                            range=["circle", "diamond"])),
    tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("point:N", title=" "),
             alt.Tooltip("vs_peak:Q", title="% of launch peak", format=".0%")])
peak_rule = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=MUTED, strokeDash=[]).encode(x="x:Q")
above = int((comeback["latest_vs_launch_peak"] >= 1).sum())
chart_block(
    f"{len(comeback)} games made a comeback after losing more than half their players — "
    f"{above} of them were bigger than at launch in {last:%B %Y}",
    "Each row is one game. The grey circle is its lowest month after launch; the black diamond is where it "
    f"was in {last:%B %Y}. The vertical line marks the launch peak (100%). Only games that fell below half their launch "
    "peak and later climbed back to at least three-quarters of it are shown.",
    (peak_rule + rules + dots).properties(height=max(220, 26 * len(comeback))),
    "A bad first year isn't the end. Big updates, a move to free-to-play, or a new console or Steam release "
    "can bring players back — sometimes more than ever.",
)

with st.expander("All games: numbers behind these charts"):
    table = games.sort_values(["lifecycle_status", "pattern", "name"])[
        ["name", "release_month", "pattern", "retention_m6", "retention_m12", "retention_m24", "latest_vs_launch_peak"]]
    st.dataframe(
        table, hide_index=True,
        column_config={
            "name": "Game", "release_month": st.column_config.DateColumn("On Steam since", format="MMM YYYY"),
            "pattern": "Pattern after one year",
            "retention_m6": st.column_config.NumberColumn("After 6 months", format="percent"),
            "retention_m12": st.column_config.NumberColumn("After 1 year", format="percent"),
            "retention_m24": st.column_config.NumberColumn("After 2 years", format="percent"),
            "latest_vs_launch_peak": st.column_config.NumberColumn(LATEST, format="percent"),
        },
    )
    st.caption("Percentages are players as a share of the launch peak. Empty = the game hasn't been out that long, "
               "or its launch happened before our monthly data starts (e.g. Terraria, 2011).")
