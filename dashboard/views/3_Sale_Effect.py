import altair as alt
import pandas as pd
import streamlit as st

from common import (DAY_AXIS, FLAT, INK, INK_2, MUTED, OUTCOME, OUTCOME_ORDER, chart_block, coverage, game_image,
                    page_header, pct, sale_bands, scale_for, utc)
from db import query

cov = coverage()
ep = query("""
    select e.*, g.header_image_url
    from reporting.rpt_discount_effect e join marts.dim_game g using (steam_app_id)
    where e.episode_status = 'valid'
""")
ep["outcome"] = ep["sale_outcome"].map(lambda o: OUTCOME[o][0])
clean = ep[~ep["post_window_confounded"]]  # no other sale started within 4 weeks after this one
n_clean_games = clean["steam_app_id"].nunique()

page_header(
    "Do discounts bring players — and do they stay?",
    "When a game is discounted on Steam, more people buy it and start playing. The question is what "
    "happens **after the discount ends**: do the new players stick around, or does the game drop back to normal? "
    f"This uses the 5-minute player data for the {ep['steam_app_id'].nunique()} paid games where we have "
    "both prices and player counts, and at least one discount we could measure (free-to-play games are never discounted).",
    period=f"5-minute player data, {utc(cov.fine_first):%d %b %Y} – {utc(cov.fine_last):%d %b %Y} (UTC days) "
           "(a historical backfill; newer years only exist as monthly averages, which are too coarse to see a discount).",
)

# ---- Chart 1: what happened after the sale -----------------------------------------------------
share = (clean.groupby("outcome").size().reindex(OUTCOME_ORDER).fillna(0).astype(int).reset_index(name="sales"))
share["share"] = share["sales"] / share["sales"].sum()
s = share.set_index("outcome")["share"]
bars = alt.Chart(share).mark_bar(cornerRadiusEnd=4, height=24).encode(
    y=alt.Y("outcome:N", sort=OUTCOME_ORDER, title=None),
    x=alt.X("share:Q", title="Share of discounts", axis=alt.Axis(format="%", tickCount=5)),
    color=alt.Color("outcome:N", scale=scale_for(OUTCOME, OUTCOME_ORDER), legend=None),
    tooltip=[alt.Tooltip("outcome:N", title="Outcome"), alt.Tooltip("sales:Q", title="Discounts"),
             alt.Tooltip("share:Q", title="Share", format=".0%")])
labels = bars.mark_text(align="left", dx=4).encode(text=alt.Text("share:Q", format=".0%"), color=alt.value(INK_2))
chart_block(
    f"{pct(s['Stayed higher after the discount'])} of discounts left the game with more players for weeks after the discount ended",
    f"Each bar is the share of discounts that ended one way, **pooled across {len(clean)} discounts from "
    f"{n_clean_games} games** (a game with more discounts counts more). We compare players in **weeks 2–4 after** the "
    "discount with **the 14 days before it (100%)**. **Stayed higher** = more than 10% above, "
    "**back to normal** = within 10%, **no bump** = players rose less than 5% during the discount itself. "
    f"Discounts followed by another discount within 4 weeks are left out ({len(ep) - len(clean)} of them), "
    "because we can't tell which discount caused what.",
    (bars + labels).properties(height=210),
    "A discount is more than a short spike. For a large share of discounts, the game ends up with a lasting bump in "
    "players, not just a one-week rush. This is an association, though, not proof: updates or events around "
    "the same time can also bring players in.",
)

# ---- Chart 2: the typical sale, step by step ---------------------------------------------------
phases = ["Two weeks before", "During the discount", "First week after", "Weeks 2–4 after"]
typ = query("""
    select discount_group, phase_order, phase, median_lift, n_discounts, n_games
    from reporting.rpt_discount_typical
    order by discount_group, phase_order
""")
typ["level"] = 1 + typ["median_lift"]
prof = typ[typ["discount_group"] == "all"].reset_index(drop=True)
prof["phase"] = phases  # phase_order 1-4
lift = typ.set_index(["discount_group", "phase"])["median_lift"]
x = alt.X("phase:N", sort=phases, title=None, axis=alt.Axis(labelAngle=0))
y = alt.Y("level:Q", title="Players vs. before the discount", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0.9, max(1.3, prof["level"].max() + 0.08)]))
ref = alt.Chart(pd.DataFrame({"level": [1.0]})).mark_rule(color=MUTED).encode(y=y)
line = alt.Chart(prof).mark_line(color=INK, strokeWidth=2.5, point=alt.OverlayMarkDef(size=90, filled=True, color=INK)).encode(
    x=x, y=y, tooltip=[alt.Tooltip("phase:N", title=" "), alt.Tooltip("level:Q", title="vs. before", format=".0%")])
vals = alt.Chart(prof).mark_text(dy=-14, color=INK, fontWeight="bold").encode(
    x=x, y=y, text=alt.Text("level:Q", format=".0%"))

d_dur, l_dur = lift["75_or_more", "during"], lift["under_50", "during"]
d_post, l_post = lift["75_or_more", "weeks_2_4_after"], lift["under_50", "weeks_2_4_after"]
discount_note = (
    f"Deeper discounts help a little: discounts of 75% or more brought a median {pct(d_dur, True)} during the discount, "
    f"against {pct(l_dur, True)} for discounts under 50%. Weeks later the gap is "
    f"{pct(d_post, True)} vs. {pct(l_post, True)}."
)
chart_block(
    f"A typical discount lifts players by {pct(prof.level[1] - 1)}; 2–4 weeks after it ends, "
    f"{pct(prof.level[3] - 1)} extra are still playing",
    "The line follows the typical discount through four stages. **100% = each discount's own baseline: the average "
    "daily players in the 14 days before it started.** Each point is the **median across "
    f"{int(prof['n_discounts'][0])} discounts from {int(prof['n_games'][0])} games**, pooled (the same discounts as "
    "the chart above).",
    (ref + line + vals).properties(height=300),
    "The bump doesn't stop when the discount does: people who bought at a discount keep playing, so the peak is often "
    "in the week after. Then the extra players drift away over the following weeks. " + discount_note,
)

# ---- Chart 3: one game, each measured discount on its own pre-discount baseline -----------------
# Fragment: picking a game or period redraws only this section, not the whole page.
@st.fragment
def game_detail_section():
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

    daily = query("""select sale_episode_key, activity_date, phase, avg_players, baseline_avg, vs_baseline,
                            sale_start, sale_end, max_discount_pct, lift_during
                     from reporting.rpt_discount_effect_daily where steam_app_id = ? order by activity_date""",
                  (int(g.steam_app_id),))
    sales = query("""select sale_start, sale_end, max_discount_pct
                     from reporting.rpt_discount_effect where steam_app_id = ?""", (int(g.steam_app_id),))
    daily["activity_date"] = pd.to_datetime(daily["activity_date"])
    if year != "All":
        daily = daily[daily["activity_date"].dt.year == int(year)]
    gep = ep[ep["steam_app_id"] == g.steam_app_id]
    bumped = int((gep["lift_during"] >= 0.05).sum())

    left, right = st.columns([1, 4])
    with left:
        game_image(g.header_image_url, width=220)
        st.metric("Discounts we could measure", f"{len(gep)}")
        st.metric("Typical bump during a discount", pct(gep["lift_during"].median(), True),
                  help="Median of this game's measured discounts. Each discount's bump = its average on the discount "
                       "days, against the 14 days before it (the 100% of the chart).")
    with right:
        if daily.empty:
            st.info("No measured discount for this game in the selected period.")
        else:
            x_dom = [daily["activity_date"].min(), daily["activity_date"].max()]
            x = alt.X("activity_date:T", title=DAY_AXIS, scale=alt.Scale(domain=x_dom),
                      axis=alt.Axis(format="%b %Y", tickCount="month"))
            ref = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=MUTED, strokeWidth=1).encode(y="y:Q")
            lines = alt.Chart(daily).mark_line(color=FLAT, strokeWidth=1.6).encode(
                x=x, y=alt.Y("vs_baseline:Q", title="Players vs. the 14 days before the discount", axis=alt.Axis(format="%")),
                detail="sale_episode_key:N",
                tooltip=[alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
                         alt.Tooltip("vs_baseline:Q", title="vs. before the discount", format=".0%"),
                         alt.Tooltip("avg_players:Q", title="Players online (daily average)", format=",.0f"),
                         alt.Tooltip("baseline_avg:Q", title="14 days before (100%)", format=",.0f"),
                         alt.Tooltip("sale_start:T", title="Discount started", format="%d %b %Y"),
                         alt.Tooltip("lift_during:Q", title="This discount's bump", format="+.0%")])
            chart_block(
                f"{game}: players rose during {bumped} of its {len(gep)} measurable discounts",
                "Each blue line is one measured discount, from 2 weeks before it to 4 weeks after it ends. "
                "**100% = that discount's own baseline: the average daily players in the 14 days before it started** "
                "(the same baseline as the numbers on the left). Not combined: one line per discount. Yellow bands are "
                "all the days the game was discounted on Steam; discounts we couldn't measure (another discount just "
                "before, or days missing) have a band but no line. Days are UTC. Hover a line for the numbers.",
                alt.layer(*sale_bands(sales, x_dom), ref, lines).resolve_scale(color="independent").properties(height=300),
                "If discounts bring players, each line should jump above 100% inside its yellow band. "
                "Watch whether it drops straight back to 100% afterwards, or stays up for a while.",
            )


game_detail_section()

with st.expander("Every measured discount (numbers behind these charts)"):
    t = ep.sort_values(["name", "sale_start"])[["name", "sale_start", "sale_days", "max_discount_pct",
                                                "lift_during", "lift_post_late", "outcome", "post_window_confounded"]]
    st.dataframe(t, hide_index=True, column_config={
        "name": "Game", "sale_start": st.column_config.DateColumn("Discount started", format="D MMM YYYY"),
        "sale_days": "Days", "max_discount_pct": st.column_config.NumberColumn("Discount", format="%d%%"),
        "lift_during": st.column_config.NumberColumn("During the discount", format="percent"),
        "lift_post_late": st.column_config.NumberColumn("Weeks 2–4 after", format="percent"),
        "outcome": "Outcome", "post_window_confounded": "Another discount soon after",
    })
    st.caption("Percentages are the change in players compared with the 14 days before the discount (100%). UTC days.")
