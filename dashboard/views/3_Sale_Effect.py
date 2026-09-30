import altair as alt
import pandas as pd
import streamlit as st

from common import (DAY_AXIS, FLAT, INK_2, OUTCOME, OUTCOME_ORDER, chart_block, coverage, game_image, middle_row,
                    page_header, pct, players, sale_bands, scale_for, utc)
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

# ---- Header metrics: the typical discount, pooled median over clean discounts (rpt_discount_typical) -------------
typ = query("""
    select phase, median_lift, mean_lift, n_discounts, n_games
    from reporting.rpt_discount_typical
    where discount_group = 'all' and phase in ('during', 'weeks_2_4_after')
""").set_index("phase")


def typ_help(phase: str) -> str:
    r = typ.loc[phase]
    return (f"Median of {int(r.n_discounts)} discounts across {int(r.n_games)} games: half of the discounts rose "
            "more, half less. Median rather than average because a few extreme cases (e.g. Witcher 3 in Dec 2019, "
            f"the Netflix series) would pull an average up. Average: {pct(r.mean_lift, True)}.")


m1, m2, _ = st.columns([1, 1, 2])
m1.metric("During a discount", pct(typ.loc["during", "median_lift"], True), help=typ_help("during"), border=True)
m2.metric("2–4 weeks after", pct(typ.loc["weeks_2_4_after", "median_lift"], True), help=typ_help("weeks_2_4_after"),
          border=True)

# ---- Depth KPIs: median bump during the discount by how deep it was (rpt_discount_by_depth) ----------------
depth = query("""
    select depth_label, n_discounts, median_lift_during, few_cases
    from reporting.rpt_discount_by_depth order by bucket_order
""")
st.caption("**During a discount, by how deep it was** (median bump, same discounts as above)")
for col, r in zip(st.columns([1, 1, 1, 1])[:3], depth.itertuples()):
    value = pct(r.median_lift_during, True) if r.n_discounts else "–"
    if r.few_cases:
        col.markdown(f":gray[{r.depth_label}]  \n:gray[**{value}** · n = {r.n_discounts} · few cases]")
    else:
        col.markdown(f"{r.depth_label}  \n**{value}** :gray[· n = {r.n_discounts}]")

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
    "Each bar is the share of discounts that ended one way: players in **weeks 2–4 after** the discount compared "
    "with **the 14 days before it**.",
    (bars + labels).properties(height=210),
    "A discount is more than a short spike. For a large share of discounts, the game ends up with a lasting bump in "
    "players, not just a one-week rush. This is an association, though, not proof: updates or events around "
    "the same time can also bring players in.",
    details=(f"Pooled across {len(clean)} discounts from {n_clean_games} games (a game with more discounts counts "
             "more). **Stayed higher** = more than 10% above the 14 days before, **back to normal** = within 10%, "
             "**no bump** = players rose less than 5% during the discount itself. Discounts followed by another "
             f"discount within 4 weeks are left out ({len(ep) - len(clean)} of them), because we can't tell which "
             "discount caused what."),
)

# ---- Chart 2: one game, each measured discount against its own pre-discount baseline -------------
# Fragment: picking a game or period redraws only this section, not the whole page.
@st.fragment
def game_detail_section():
    games = (ep.groupby(["steam_app_id", "name", "header_image_url"]).size()
             .reset_index(name="sales").sort_values("name"))
    names = games["name"].tolist()
    default = next((i for i, n in enumerate(names) if n.startswith("The Witcher 3")), 0)  # Steam renames editions
    c1, c2 = st.columns([3, 1])
    with c1:
        game = st.selectbox("Look at one game", names, index=default)
    with c2:
        year = st.segmented_control("Period", ["2018", "2019", "2020", "All"], default="All", required=True)
    g = games[games["name"] == game].iloc[0]

    # the continuous line: every complete 5-minute day of the game (same days rpt_discount_effect measures on)
    days = query("""select activity_date, avg_players from marts.fact_player_activity_daily
                    where steam_app_id = ? and data_resolution = '5min' and is_complete_day
                    order by activity_date""", (int(g.steam_app_id),))
    # the discount windows (14 days before to 28 days after each measured discount) with their baselines
    daily = query("""select sale_episode_key, activity_date, avg_players, baseline_avg,
                            sale_start, sale_end, max_discount_pct
                     from reporting.rpt_discount_effect_daily where steam_app_id = ? order by activity_date""",
                  (int(g.steam_app_id),))
    sales = query("""select sale_start, sale_end, max_discount_pct
                     from reporting.rpt_discount_effect where steam_app_id = ?""", (int(g.steam_app_id),))
    days["activity_date"] = pd.to_datetime(days["activity_date"])
    for c in ["activity_date", "sale_start", "sale_end"]:
        daily[c] = pd.to_datetime(daily[c])
    if year != "All":
        days = days[days["activity_date"].dt.year == int(year)]
        daily = daily[daily["activity_date"].dt.year == int(year)]
    daily["discount"] = [f"{a:%d %b} – {e:%d %b %Y}, up to {p:.0f}% off"
                         for a, e, p in zip(daily["sale_start"], daily["sale_end"], daily["max_discount_pct"])]
    daily["vs_base"] = [f"{players(b)} a day ({pct(v / b)} of it on this day)"
                        for v, b in zip(daily["avg_players"], daily["baseline_avg"])]
    # a day inside two overlapping windows lists both
    windows = daily.groupby("activity_date").agg(discount=("discount", " | ".join), baseline=("vs_base", " | ".join))
    gep = ep[ep["steam_app_id"] == g.steam_app_id]
    bumped = int((gep["lift_during"] >= 0.05).sum())
    gmid = middle_row(gep, "lift_during")

    left, right = st.columns([1, 4])
    with left:
        game_image(g.header_image_url, width=220)
        st.metric("Discounts we could measure", f"{len(gep)}")
        st.metric("Typical discount bump", pct(gep["lift_during"].median(), True),
                  help="Median bump during a discount, over this game's measured discounts. Each discount's bump = its "
                       "average on the discount days, against the 14 days before it (the 100% of the chart).")
        st.caption(f"In players, the median discount ({pd.Timestamp(gmid.sale_start):%d %b %Y}, "
                   f"{pct(gmid.lift_during, True)}): {players(gmid.baseline_avg)} a day before → "
                   f"{players(gmid.during_avg)} during.")
    with right:
        if days.empty:
            st.info("No daily player data for this game in the selected period.")
        else:
            x_dom = [days["activity_date"].min(), days["activity_date"].max()]
            # one row per calendar day: days without complete data become empty rows, so the line breaks there
            # instead of joining across the gap
            full = pd.date_range(x_dom[0], x_dom[1], freq="D")
            n_missing = len(full) - days["activity_date"].nunique()
            line_days = (days.set_index("activity_date").reindex(full).rename_axis("activity_date")
                         .join(windows).reset_index())
            x = alt.X("activity_date:T", title=DAY_AXIS, scale=alt.Scale(domain=x_dom),
                      axis=alt.Axis(format="%b %Y", tickCount="month"))
            lines = alt.Chart(line_days).mark_line(color=FLAT, strokeWidth=1.6).encode(
                x=x, y=alt.Y("avg_players:Q", title="Players online (daily average)", axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("activity_date:T", title="Day (UTC)", format="%a %d %b %Y"),
                         alt.Tooltip("avg_players:Q", title="Players online (daily average)", format=",.0f"),
                         alt.Tooltip("baseline:N", title="14-day baseline"),
                         alt.Tooltip("discount:N", title="Discount")])
            # each window's 100%: a dashed line at its baseline, spanning the days of that window shown
            base = (daily.groupby(["sale_episode_key", "baseline_avg", "discount"], as_index=False)
                    .agg(start=("activity_date", "min"), end=("activity_date", "max")))
            base_lines = alt.Chart(base).mark_rule(color=INK_2, strokeDash=[4, 3], strokeWidth=1.3).encode(
                x="start:T", x2="end:T", y="baseline_avg:Q",
                tooltip=[alt.Tooltip("baseline_avg:Q", title="14-day baseline (players a day)", format=",.0f"),
                         alt.Tooltip("discount:N", title="Discount")])
            chart_block(
                f"{game}: players rose during {bumped} of its {len(gep)} measurable discounts",
                "The blue line is players online each day; yellow bands are Steam discounts. Each dashed line is one "
                "measured discount's baseline, the average daily players in the 14 days before it.",
                alt.layer(*sale_bands(sales, x_dom), base_lines, lines).resolve_scale(color="independent")
                .properties(height=300),
                "If discounts bring players, the blue line rises above its dashed baseline inside the yellow band. "
                "Watch whether it drops straight back to the baseline afterwards, or stays up for a while.",
                details=("The dashed baseline is the 100% behind the percentages on the left; it spans the discount's "
                         "window, from 2 weeks before it to 4 weeks after it ends. Discounts we couldn't measure "
                         "(another discount just before, or days missing) have a band but no dashed line. Hover the "
                         "blue line for players; inside a window also the baseline and the % of it on that day. "
                         + (f"Gaps in the line are days without complete data ({n_missing} in this period)."
                            if n_missing else "No days are missing in this period.")),
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
    st.caption("Percentages are the change in players compared with the 14 days before the discount (100%).")
