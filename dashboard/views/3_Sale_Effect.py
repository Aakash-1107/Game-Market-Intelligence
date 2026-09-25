import altair as alt
import pandas as pd
import streamlit as st

from common import (INK, INK_2, MUTED, OUTCOME, OUTCOME_ORDER, chart_block, coverage, daily_activity, event_chart,
                    game_image, local, page_header, pct, scale_for)
from db import query

cov = coverage()
page_header(
    "Do sales bring players — and do they stay?",
    "When a game is discounted on Steam, more people buy it and start playing. The question is what "
    "happens **after the sale ends**: do the new players stick around, or does the game drop back to normal? "
    "This uses the 5-minute player data for the 14 paid games where we have "
    "both prices and player counts (free-to-play games never go on sale).",
    period=f"5-minute player data, {local(cov.fine_first):%d %b %Y} – {local(cov.fine_last):%d %b %Y} "
           "(a historical backfill; newer years only exist as monthly averages, which are too coarse to see a sale).",
)

ep = query("""
    select e.*, g.header_image_url
    from an_sale_effect e join dim_game g using (steam_app_id)
    where e.episode_status = 'valid'
""")
ep["outcome"] = ep["sale_outcome"].map(lambda o: OUTCOME[o][0])
clean = ep[~ep["post_window_confounded"]]  # no other sale started within 4 weeks after this one

# ---- Chart 1: what happened after the sale -----------------------------------------------------
share = (clean.groupby("outcome").size().reindex(OUTCOME_ORDER).fillna(0).astype(int).reset_index(name="sales"))
share["share"] = share["sales"] / share["sales"].sum()
s = share.set_index("outcome")["share"]
bars = alt.Chart(share).mark_bar(cornerRadiusEnd=4, height=24).encode(
    y=alt.Y("outcome:N", sort=OUTCOME_ORDER, title=None),
    x=alt.X("share:Q", title="Share of sales", axis=alt.Axis(format="%", tickCount=5)),
    color=alt.Color("outcome:N", scale=scale_for(OUTCOME, OUTCOME_ORDER), legend=None),
    tooltip=[alt.Tooltip("outcome:N", title="Outcome"), alt.Tooltip("sales:Q", title="Sales"),
             alt.Tooltip("share:Q", title="Share", format=".0%")])
labels = bars.mark_text(align="left", dx=4).encode(text=alt.Text("share:Q", format=".0%"), color=alt.value(INK_2))
chart_block(
    f"{pct(s['Stayed higher after the sale'])} of sales left the game with more players for weeks after the sale ended",
    f"Each bar is the share of {len(clean)} sales that ended one way. We compare players "
    "1–4 weeks after the sale with the two weeks before it. **Stayed higher** = more than 10% above, "
    "**back to normal** = within 10%, **no bump** = players rose less than 5% during the sale itself. "
    f"Sales followed by another sale within 4 weeks are left out ({len(ep) - len(clean)} of them), "
    "because we can't tell which sale caused what.",
    (bars + labels).properties(height=210),
    "A sale is more than a short spike. For a large share of sales, the game ends up with a lasting bump in "
    "players, not just a one-week rush. This is an association, though, not proof: updates or events around "
    "the same time can also bring players in.",
)

# ---- Chart 2: the typical sale, step by step ---------------------------------------------------
phases = ["Two weeks before", "During the sale", "First week after", "Weeks 2–4 after"]
prof = pd.DataFrame({
    "phase": phases,
    "level": [1.0, 1 + clean["lift_during"].median(), 1 + clean["lift_post_early"].median(),
              1 + clean["lift_post_late"].median()],
})
x = alt.X("phase:N", sort=phases, title=None, axis=alt.Axis(labelAngle=0))
y = alt.Y("level:Q", title="Players vs. before the sale", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0.9, max(1.3, prof["level"].max() + 0.08)]))
ref = alt.Chart(pd.DataFrame({"level": [1.0]})).mark_rule(color=MUTED).encode(y=y)
line = alt.Chart(prof).mark_line(color=INK, strokeWidth=2.5, point=alt.OverlayMarkDef(size=90, filled=True, color=INK)).encode(
    x=x, y=y, tooltip=[alt.Tooltip("phase:N", title=" "), alt.Tooltip("level:Q", title="vs. before", format=".0%")])
vals = alt.Chart(prof).mark_text(dy=-14, color=INK, fontWeight="bold").encode(
    x=x, y=y, text=alt.Text("level:Q", format=".0%"))

deep, light = clean[clean["max_discount_pct"] >= 75], clean[clean["max_discount_pct"] < 50]
d_dur, l_dur = deep["lift_during"].median(), light["lift_during"].median()
d_post, l_post = deep["lift_post_late"].median(), light["lift_post_late"].median()
discount_note = (
    f"Deeper discounts help a little: sales of 75% or more brought a median {pct(d_dur, True)} during the sale, "
    f"against {pct(l_dur, True)} for discounts under 50%. Weeks later the gap is "
    f"{pct(d_post, True)} vs. {pct(l_post, True)}."
)
chart_block(
    f"A typical sale lifts players by {pct(prof.level[1] - 1)}; 2–4 weeks after it ends, "
    f"{pct(prof.level[3] - 1)} extra are still playing",
    "The line follows the typical (middle) sale through four stages. 100% is the player level in the two weeks "
    "before the sale. Each point is the middle value across all the sales on the chart above.",
    (ref + line + vals).properties(height=300),
    "The bump doesn't stop when the sale does: people who bought on sale keep playing, so the peak is often "
    "in the week after. Then the extra players drift away over the following weeks. " + discount_note,
)

# ---- Chart 3: one game, sales shaded behind its players (event-shading pattern) ----------------
games = (ep.groupby(["steam_app_id", "name", "header_image_url"]).size()
         .reset_index(name="sales").sort_values("name"))
names = games["name"].tolist()
default = names.index("The Witcher 3: Wild Hunt - Complete Edition") if "The Witcher 3: Wild Hunt - Complete Edition" in names else 0
c1, c2 = st.columns([3, 1])
with c1:
    game = st.selectbox("Look at one game", names, index=default)
with c2:
    year = st.segmented_control("Period", ["2018", "2019", "2020", "All"], default="2019", required=True)
g = games[games["name"] == game].iloc[0]

daily = daily_activity(int(g.steam_app_id))
sales = query("""select sale_start, sale_end, max_discount_pct, lift_during, sale_outcome, episode_status
                 from an_sale_effect where steam_app_id = ?""", (int(g.steam_app_id),))
if year != "All":
    daily = daily[daily["day"].dt.year == int(year)]
gep = ep[ep["steam_app_id"] == g.steam_app_id]
bumped = int((gep["lift_during"] >= 0.05).sum())

left, right = st.columns([1, 4])
with left:
    game_image(g.header_image_url, width=220)
    st.metric("Sales we could measure", f"{len(gep)}")
    st.metric("Typical bump during a sale", pct(gep["lift_during"].median(), True))
with right:
    if daily.empty:
        st.info("No daily player data for this game in the selected period.")
    else:
        chart_block(
            f"{game}: players rose during {bumped} of its {len(gep)} measurable sales",
            "The blue line is players online compared with the game's typical level around that time "
            "(100% = typical), smoothed over 7 days to hide the weekday/weekend rhythm. Yellow bands are the days "
            "the game was on sale on Steam. Hover a band for the discount.",
            event_chart(daily, sales, smooth=True),
            "If sales bring players, the line should jump up inside the yellow bands. "
            "Watch whether it drops straight back to 100% after each band, or stays up for a while.",
        )

with st.expander("Every measured sale (numbers behind these charts)"):
    t = ep.sort_values(["name", "sale_start"])[["name", "sale_start", "sale_days", "max_discount_pct",
                                                "lift_during", "lift_post_late", "outcome", "post_window_confounded"]]
    st.dataframe(t, hide_index=True, column_config={
        "name": "Game", "sale_start": st.column_config.DateColumn("Sale started", format="D MMM YYYY"),
        "sale_days": "Days", "max_discount_pct": st.column_config.NumberColumn("Discount", format="%d%%"),
        "lift_during": st.column_config.NumberColumn("During the sale", format="percent"),
        "lift_post_late": st.column_config.NumberColumn("2–4 weeks after", format="percent"),
        "outcome": "Outcome", "post_window_confounded": "Another sale soon after",
    })
    st.caption("Percentages are the change in players compared with the two weeks before the sale.")
