import altair as alt
import pandas as pd
import streamlit as st

from common import (COUNT_AXIS, HOVER_HINT, INK, INK_2, MUTED, PATTERN, PATTERN_ORDER, baseline_range, chart_block,
                    coverage, highlight_lines, page_header, pct, scale_for, share_of, spread_labels)
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
           lowest_vs_launch_peak, has_recovery, first_recovery_month_index,
           launch_peak_avg, latest_avg_players, lowest_after_launch_players
    from reporting.rpt_game_lifecycle
""")
games["pattern"] = games["lifecycle_pattern"].map(lambda p: PATTERN.get(p, (None,))[0])

curves = query("""
    select name, lifecycle_pattern, is_settled, month_index as month_idx, vs_launch_peak as vs_peak,
           avg_players, launch_peak_avg
    from reporting.rpt_lifecycle_curve
""")
curves["pattern"] = curves["lifecycle_pattern"].map(lambda p: PATTERN[p][0])
curves["in_players"] = [share_of(f"Month {m}", v, b, "launch peak")
                        for m, v, b in zip(curves["month_idx"], curves["avg_players"], curves["launch_peak_avg"])]

# Month 0 in every caption that uses the launch peak as 100%
MONTH_0 = ("Month 0 is the calendar month of the game's Steam release date, so it is usually a partial month, "
           "or, for games that were in Early Access before their 1.0 release, it also includes Early Access days.")

# "Typical game" = median across games with at least a year of history (computed in rpt_lifecycle_typical_curve).
settled = curves[curves["is_settled"]]
median_curve = query("""
    select month_index as month_idx, median_vs_launch_peak as vs_peak, n_games as games,
           plateau_vs_launch_peak, n_games_total
    from reporting.rpt_lifecycle_typical_curve
    order by month_index
""")
mc = median_curve.set_index("month_idx")["vs_peak"]
m3 = mc.loc[3]
plateau = median_curve["plateau_vs_launch_peak"].iloc[0]  # median of the monthly medians, months 4-18
n_settled = int(median_curve["n_games_total"].iloc[0])

# ---- Chart 1: the typical curve + a few picked games ------------------------------------------
# Fragment: changing the picker reruns and redraws only this section, not the whole page.
@st.fragment
def typical_curve_section():
    default = [g for g in ["ELDEN RING", "Baldur's Gate 3", "Subnautica", "Factorio", "Rust"] if g in set(settled["name"])]
    picked = st.multiselect("Compare games against the typical curve (up to 5 is easiest to read)",
                            sorted(curves["name"].unique()), default=default)
    show_typical = st.checkbox("Show typical game", value=True)
    sel = curves[curves["name"].isin(picked)]

    x = alt.X("month_idx:Q", title="Months since the game came out on Steam", scale=alt.Scale(domain=[0, 24]),
              axis=alt.Axis(values=list(range(0, 25, 3))))
    y = alt.Y("vs_peak:Q", title="Players, as % of the launch peak", axis=alt.Axis(format="%"))
    ref = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=MUTED).encode(y="y:Q")
    typical = alt.Chart(median_curve).mark_line(color=INK, strokeWidth=3.5).encode(
        x=x, y=y, tooltip=[alt.Tooltip("month_idx:Q", title="Month"),
                           alt.Tooltip("vs_peak:Q", title="Typical game", format=".0%"),
                           alt.Tooltip("games:Q", title="Games in this month")])

    lines = alt.Chart(sel).mark_line(strokeWidth=2).encode(
        x=x, y=y, detail="name:N",
        color=alt.Color("pattern:N", title="Pattern after one year", scale=scale_for(PATTERN, PATTERN_ORDER)),
        tooltip=[alt.Tooltip("name:N", title="Game"),
                 alt.Tooltip("in_players:N", title="Players online (monthly average)"),
                 alt.Tooltip("pattern:N", title="Pattern")])
    ends = sel.loc[sel.groupby("name")["month_idx"].idxmax(), ["name", "month_idx", "vs_peak"]]
    if show_typical:
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
        "**100% = the game's busiest month within its first four months (month 0 to month 3).** "
        f"Black line = the typical game (median of {n_settled} games); thin lines = the games you picked.",
        alt.layer(ref, *highlight_lines(lines, "pattern"), *([typical] if show_typical else []), end_labels)
        .properties(height=420),
        "The launch rush is short. Most players who show up in the first weeks are gone within a few months. "
        "After that the curve flattens: the players who are left tend to stay. The small bumps at 12 and 24 months "
        "line up with the game's anniversary, when many games run discounts or release updates.",
        baseline=baseline_range(settled.drop_duplicates("name"), "launch_peak_avg", "name", "Launch peak (100%)",
                                f"the {n_settled} games behind the typical game"),
        details=(f"{MONTH_0} The typical game is the median across the {n_settled} games with at least a year of "
                 f"history, month by month; later months have fewer games ({int(mc.index.max())} months after launch "
                 f"has {int(median_curve['games'].iloc[-1])}). Thin lines are coloured by the pattern the game ends up "
                 f"in. {HOVER_HINT}"),
    )
    st.caption(f"Typical game = median of the {n_settled} games that have at least a year of "
               "history since launch, including re-releases and games that went free-to-play later.")


typical_curve_section()

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
    "Each bar counts games by where they stood one year after launch, compared with their launch peak.",
    (bars + bar_labels).properties(height=230),
    "There are two very different kinds of game. Story-driven blockbusters (played once, then finished) "
    "tend to drop fast. Online and multiplayer games that keep adding content often end up bigger than at launch.",
    details=("**Fast drop** = below 30% of the launch peak after one year, **slow fade** = 30–60%, "
             "**holds steady** = 60–100%, **keeps growing** = above 100%. \"Too new to tell\" games haven't been out "
             "for a year yet."),
)

# ---- Chart 3: comebacks ------------------------------------------------------------------------
comeback = games[games["has_recovery"] == True].copy()  # noqa: E712 (nullable boolean)
comeback = comeback.sort_values("latest_vs_launch_peak")
cb = comeback.melt(id_vars=["name", "pattern", "launch_peak_avg", "lowest_after_launch_players", "latest_avg_players"],
                   value_vars=["lowest_vs_launch_peak", "latest_vs_launch_peak"], var_name="point", value_name="vs_peak")
cb["players"] = cb["lowest_after_launch_players"].where(cb["point"] == "lowest_vs_launch_peak", cb["latest_avg_players"])
cb["point"] = cb["point"].map({"lowest_vs_launch_peak": "Lowest point after launch",
                               "latest_vs_launch_peak": LATEST})
cb["in_players"] = [share_of(p, v, b, "launch peak") for p, v, b in zip(cb["point"], cb["players"], cb["launch_peak_avg"])]
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
    tooltip=[alt.Tooltip("name:N", title="Game"),
             alt.Tooltip("in_players:N", title="Players online (monthly average)")])
peak_rule = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=MUTED, strokeDash=[]).encode(x="x:Q")
above = int((comeback["latest_vs_launch_peak"] >= 1).sum())
chart_block(
    f"{len(comeback)} games made a comeback after losing more than half their players — "
    f"{above} of them were bigger than at launch in {last:%B %Y}",
    f"Grey circle = the game's lowest month after launch, black diamond = {last:%B %Y}. "
    "**100% = the game's busiest month within its first four months (month 0 to month 3).**",
    (peak_rule + rules + dots).properties(height=max(220, 26 * len(comeback))),
    "A bad first year isn't the end. Big updates, a move to free-to-play, or a new console or Steam release "
    "can bring players back — sometimes more than ever.",
    baseline=baseline_range(comeback, "launch_peak_avg", "name", "Launch peak (100%)", f"these {len(comeback)} games"),
    details=(f"One row per game, {len(comeback)} games: only games that fell below half their launch peak and later "
             f"climbed back to at least three-quarters of it. {MONTH_0}"),
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
