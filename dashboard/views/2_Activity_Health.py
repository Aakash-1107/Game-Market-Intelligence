import altair as alt
import pandas as pd
import streamlit as st

from common import (COUNT_AXIS, HEALTH, HEALTH_ORDER, INK_2, MUTED, chart_block, page_header, pct, scale_for,
                    spread_labels)
from db import query

bounds = query("select min(window_start) as window_start, max(window_end) as window_end from an_activity_health").iloc[0]
window_start, window_end = pd.Timestamp(bounds.window_start), pd.Timestamp(bounds.window_end)
period = f"{window_start:%b %Y} – {window_end:%b %Y}"
# current_level_3m = the last 3 months of the window (month_num >= 9 in an_activity_health)
recent = f"{window_end - pd.DateOffset(months=2):%b}–{window_end:%b %Y}"
next_month = window_end + pd.DateOffset(months=1)

page_header(
    "Activity health: which games are growing, and which are shrinking?",
    "This page looks at **the last 12 complete months only** and sorts games by the direction their player "
    "numbers are heading. Two games with the same number of players can be in very different "
    "shape: one steadily gaining, one steadily losing.",
    period=f"{period} (12 complete months). \"Players online\" on this page means the {recent} average. "
           f"{next_month:%B %Y} isn't complete yet, so it isn't included; see *Right now* on the Market overview.",
)

h = query("""
    select steam_app_id, name, health_class, window_start, window_end, start_level_3m, current_level_3m,
           change_12m_pct, trend_monthly_pct, size_tier
    from an_activity_health
""")
h["health"] = h["health_class"].map(lambda c: HEALTH[c][0])

judged = h[h["health"] != "Too new to judge"]
counts = h.groupby("health").size().reindex(HEALTH_ORDER).fillna(0).astype(int).reset_index(name="games")
n = counts.set_index("health")["games"]
declining_names = judged.loc[judged["health"] == "Declining", "name"].tolist()

# ---- Chart 1: how many games in each class ----------------------------------------------------
bars = alt.Chart(counts).mark_bar(cornerRadiusEnd=4, height=22).encode(
    y=alt.Y("health:N", sort=HEALTH_ORDER, title=None),
    x=alt.X("games:Q", title="Number of games", axis=COUNT_AXIS),
    color=alt.Color("health:N", scale=scale_for(HEALTH, HEALTH_ORDER), legend=None),
    tooltip=[alt.Tooltip("health:N", title="Health"), alt.Tooltip("games:Q", title="Games")])
labels = bars.mark_text(align="left", dx=4).encode(text="games:Q", color=alt.value(INK_2))
decl_txt = (f"only {n['Declining']} ({', '.join(declining_names)}) is clearly declining" if 0 < n["Declining"] <= 2
            else f"{n['Declining']} are clearly declining")
chart_block(
    f"Most games are holding steady: {n['Stable']} of {len(judged)} were stable over the last year, and {decl_txt}",
    f"Each bar counts games by the direction of their player numbers over {period}. "
    "**Growing / Declining** = a steady rise or fall of at least 3% a month. **Stable** = less than 3% a month either way. "
    "**Up-and-down** = big swings with no clear direction. Games out for less than a year are \"too new to judge\".",
    (bars + labels).properties(height=230),
    "The established games in this set are mostly in a steady state. Big moves over a year are rare. "
    "When they happen, they usually come from a major update or re-launch, not from a slow drift.",
)

# ---- Chart 2: same size, different direction ---------------------------------------------------
plot = judged.dropna(subset=["current_level_3m", "change_12m_pct"]).copy()
CAP = 1.5
plot["y"] = plot["change_12m_pct"].clip(upper=CAP)
clipped = plot[plot["change_12m_pct"] > CAP]

zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=MUTED).encode(y="y:Q")
pts = alt.Chart(plot).mark_point(filled=True, size=120, opacity=0.9, stroke="white", strokeWidth=1.2).encode(
    x=alt.X("current_level_3m:Q", title=f"Players online, {recent} average (log scale)",
            scale=alt.Scale(type="log", domain=[1_500, 1_200_000]),
            axis=alt.Axis(format="~s", values=[3_000, 10_000, 30_000, 100_000, 300_000, 1_000_000])),
    y=alt.Y("y:Q", title="Change over the last 12 months", axis=alt.Axis(format="+%"),
            scale=alt.Scale(domain=[-1, CAP])),
    color=alt.Color("health:N", title=None, scale=scale_for(HEALTH, HEALTH_ORDER[:4])),
    shape=alt.Shape("health:N", title=None, scale=alt.Scale(domain=HEALTH_ORDER[:4],
                                                             range=["triangle-up", "circle", "diamond", "triangle-down"])),
    tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("health:N", title="Health"),
             alt.Tooltip("current_level_3m:Q", title=f"Players online, {recent} avg", format=",.0f"),
             alt.Tooltip("change_12m_pct:Q", title="Change over 12 months", format="+.0%")])
note = alt.Chart(clipped).mark_text(align="left", dx=8, dy=-2, fontSize=11, color=INK_2).encode(
    x="current_level_3m:Q", y="y:Q",
    text=alt.Text("label:N")).transform_calculate(
    label="datum.name + ' (' + format(datum.change_12m_pct, '+.0%') + ', off the scale)'")

big = plot.sort_values("current_level_3m", ascending=False)
chart_block(
    "Games of the same size can be heading in opposite directions",
    f"Each dot is one game. Further right = more players in {recent} (each gridline is about 3× the one before). "
    f"Higher up = gained players over {period} ({recent} compared with the first 3 months), below the grey line = lost players. "
    "The colour (and shape) shows the health class, based on how steady the trend was — not just start vs. end.",
    (zero + pts + note).properties(height=440),
    "Size doesn't predict direction. Among games with a similar number of players, some are clearly "
    "growing while others shrink or swing around. Player count alone is a poor guide to a game's health.",
)

# ---- Chart 3: trend lines for picked games -----------------------------------------------------
defaults = [g for g in ["Apex Legends™", "No Man's Sky", "Stardew Valley", "ELDEN RING", "Counter-Strike 2"]
            if g in set(judged["name"])]
picked = st.multiselect("Pick games to compare (up to 5 is easiest to read)", sorted(judged["name"]), default=defaults)
trend = query("""
    select h.name, h.health_class, m.activity_month, m.avg_players / h.start_level_3m as vs_start
    from an_activity_health h
    join fact_player_activity_monthly m
      on m.steam_app_id = h.steam_app_id and m.activity_month between h.window_start and h.window_end
    where h.start_level_3m > 0
""")
trend["health"] = trend["health_class"].map(lambda c: HEALTH[c][0])
tsel = trend[trend["name"].isin(picked)].copy()
tsel["activity_month"] = pd.to_datetime(tsel["activity_month"])

if tsel.empty:
    st.info("Pick at least one game above to see its 12-month trend.")
else:
    last = tsel.loc[tsel.groupby("name")["activity_month"].idxmax()]
    top, bottom = last.sort_values("vs_start").iloc[-1], last.sort_values("vs_start").iloc[0]
    x = alt.X("activity_month:T", title=None, axis=alt.Axis(format="%b %Y"))
    y = alt.Y("vs_start:Q", title="Players vs. the start of the year", axis=alt.Axis(format="%"))
    base = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=MUTED).encode(y="y:Q")
    lines = alt.Chart(tsel).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=x, y=y, detail="name:N",
        color=alt.Color("health:N", title=None, scale=scale_for(HEALTH, HEALTH_ORDER)),
        tooltip=[alt.Tooltip("name:N", title="Game"), alt.Tooltip("activity_month:T", title="Month", format="%b %Y"),
                 alt.Tooltip("vs_start:Q", title="vs. start of the year", format=".0%"),
                 alt.Tooltip("health:N", title="Health")])
    labels = spread_labels(last, "vs_start", min_gap=max(1.0, tsel["vs_start"].max()) * 0.06)
    end_labels = alt.Chart(labels).mark_text(align="left", dx=8, fontSize=11, color=INK_2).encode(
        x=x, y=alt.Y("label_y:Q"), text="name:N")
    title = (f"Over the same 12 months, {top['name']} went to {pct(top['vs_start'])} of its starting level "
             f"while {bottom['name']} went to {pct(bottom['vs_start'])}") if len(last) > 1 else \
        f"{top['name']} is at {pct(top['vs_start'])} of where it started the year"
    chart_block(
        title,
        "Each line is one game. 100% (grey line) is its average over the first three months of the window. "
        "A line above 100% means more players than at the start of the year. Colours match the health classes above.",
        (base + lines + end_labels).properties(height=380),
        "Putting every game on its own starting point shows the direction clearly, even for games whose "
        "player counts differ by a factor of a hundred.",
    )

with st.expander("All games: numbers behind these charts"):
    st.dataframe(
        h.sort_values(["health", "current_level_3m"], ascending=[True, False])[
            ["name", "health", "current_level_3m", "change_12m_pct", "trend_monthly_pct"]],
        hide_index=True,
        column_config={
            "name": "Game", "health": "Health",
            "current_level_3m": st.column_config.NumberColumn(f"Players online, {recent} avg", format="localized"),
            "change_12m_pct": st.column_config.NumberColumn("Change over 12 months", format="percent"),
            "trend_monthly_pct": st.column_config.NumberColumn("Trend per month", format="percent"),
        },
    )
