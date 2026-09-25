import altair as alt
import pandas as pd
import streamlit as st

from common import (FLAT, HEALTH, INK, INK_2, MUTED, PATTERN, chart_block, coverage, live_snapshot, local,
                    page_header, pct)
from db import query

cov = coverage()
live_last = local(cov.live_last)
page_header(
    "Game explorer", "Pick any game to see everything we know about it: players, prices, and reviews.",
    period=f"monthly players {cov.monthly_first:%b %Y} – {cov.monthly_last:%b %Y} (complete months) · "
           f"live hourly players {local(cov.live_first):%d %b} – {live_last:%d %b %Y, %H:%M}",
)

games = query("""
    select g.*, l.lifecycle_pattern, h.health_class
    from dim_game g
    left join an_game_lifecycle l using (steam_app_id)
    left join an_activity_health h using (steam_app_id)
    order by g.name
""")
names = games["name"].tolist()
game = st.selectbox("Game", names, index=names.index("Cyberpunk 2077") if "Cyberpunk 2077" in names else 0)
g = games[games["name"] == game].iloc[0]
app_id = int(g.steam_app_id)


def chip(label: str, colour: str) -> str:
    return (f"<span style='display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;border-radius:12px;"
            f"border:1.5px solid {colour};color:{INK};font-size:0.85rem'>"
            f"<span style='color:{colour}'>●</span> {label}</span>")


# ---- Header -------------------------------------------------------------------------------------
img, info = st.columns([2, 3])
with img:
    if g.header_image_url:
        st.image(g.header_image_url, width="stretch")
with info:
    st.subheader(g["name"])
    if g.short_description:
        st.markdown(g.short_description)
    facts = [f"**Genres:** {g.steam_genres or '—'}",
             f"**Made by:** {g.developers or '—'}",
             f"**On Steam since:** {g.release_date:%d %b %Y}" if pd.notna(g.release_date) else "**On Steam since:** —",
             "**Price model:** free-to-play" if g.is_free else "**Price model:** paid"]
    st.markdown("  \n".join(facts))
    chips = []
    if isinstance(g.lifecycle_pattern, str) and g.lifecycle_pattern in PATTERN:
        chips.append(chip(f"After launch: {PATTERN[g.lifecycle_pattern][0]}", PATTERN[g.lifecycle_pattern][1]))
    if isinstance(g.health_class, str):
        chips.append(chip(f"Last 12 months: {HEALTH[g.health_class][0]}", HEALTH[g.health_class][1]))
    if chips:
        st.markdown("".join(chips), unsafe_allow_html=True)

# ---- Headline numbers ---------------------------------------------------------------------------
snap = live_snapshot()
live = snap[snap["steam_app_id"] == app_id]
live = live.iloc[0] if not live.empty else None
k = query("""
    select
      (select max(avg_players) from fact_player_activity_monthly where steam_app_id = $1) as best_month,
      (select avg(voted_up::int) from fact_reviews where steam_app_id = $1) as positive,
      (select count(*) from fact_reviews where steam_app_id = $1) as n_reviews,
      (select avg(raw_score) from fact_critic_review where steam_app_id = $1 and score_base is not null) as critic,
      (select count(*) from fact_critic_review where steam_app_id = $1 and score_base is not null) as n_critic
""", (app_id,)).iloc[0]
m1, m2, m3, m4 = st.columns(4)
if live is not None:
    vs = live.vs_last_month
    m1.metric("Players online now", f"{live.now_players:,.0f}",
              f"{pct(vs, signed=True)} this week vs. {live.last_month:%b %Y}" if pd.notna(vs) else None,
              help=f"Latest hourly reading ({local(live.now_at):%d %b %Y, %H:%M}). The change compares the average "
                   f"of the last 7 days ({live.avg_7d:,.0f}) with the last complete month's average.", border=True)
else:
    m1.metric("Players online now", "—", help="No live readings for this game.", border=True)
m2.metric("Busiest month ever", f"{k.best_month:,.0f}" if pd.notna(k.best_month) else "—",
          help="Highest monthly average of players online at the same time.", border=True)
m3.metric("Positive reviews", f"{k.positive:.0%}" if k.n_reviews else "—",
          help=f"Share of the {k.n_reviews:,} most recent Steam reviews that recommend the game.", border=True)
m4.metric("Critic score", f"{k.critic:.0f} / 100" if k.n_critic else "Not covered",
          help="Average score from professional reviewers (OpenCritic). Only 12 games are covered.", border=True)

# ---- Players over time --------------------------------------------------------------------------
monthly = query("""select activity_month, avg_players from fact_player_activity_monthly
                   where steam_app_id = ? order by activity_month""", (app_id,))
if monthly.empty:
    st.info(f"No monthly player history yet for {game} — it's too new. Only the last few weeks of hourly data exist.")
else:
    monthly["activity_month"] = pd.to_datetime(monthly["activity_month"])
    peak = monthly.loc[monthly["avg_players"].idxmax()]
    latest = monthly.iloc[-1]
    x = alt.X("activity_month:T", title=None, axis=alt.Axis(format="%Y", tickCount="year"))
    area = alt.Chart(monthly).mark_area(color=FLAT, opacity=0.12).encode(x=x, y="avg_players:Q")
    line = alt.Chart(monthly).mark_line(color=FLAT, strokeWidth=2).encode(
        x=x, y=alt.Y("avg_players:Q", title="Players online (monthly average)", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("activity_month:T", title="Month", format="%b %Y"),
                 alt.Tooltip("avg_players:Q", title="Players online", format=",.0f")])
    peak_pt = alt.Chart(pd.DataFrame([peak])).mark_point(filled=True, size=90, color=INK).encode(
        x=x, y="avg_players:Q")
    peak_lbl = alt.Chart(pd.DataFrame([peak])).mark_text(align="left", dx=10, dy=4, color=INK, fontSize=11).encode(
        x=x, y="avg_players:Q", text=alt.value(f"Busiest: {peak.activity_month:%b %Y}"))
    layers = [area, line, peak_pt, peak_lbl]
    if pd.notna(g.release_date) and pd.Timestamp(g.release_date) >= monthly["activity_month"].min():
        rel = pd.DataFrame({"d": [pd.Timestamp(g.release_date)]})
        layers.insert(0, alt.Chart(rel).mark_rule(color=MUTED).encode(x="d:T"))
    share_now = latest.avg_players / peak.avg_players
    chart_block(
        f"{game} was busiest in {peak.activity_month:%B %Y} with about {peak.avg_players:,.0f} players online at once; "
        f"in {latest.activity_month:%B %Y} it had {share_now:.0%} of that",
        "The line shows how many people were playing at the same moment, averaged over each month. "
        "The black dot marks the busiest month; the thin grey vertical line is when the game came out on Steam.",
        alt.layer(*layers).properties(height=300),
        "Peaks usually line up with the launch, a big update, a sale or a new season. The long flat stretches "
        "are the game's loyal core audience.",
    )

# ---- Live hourly feed ---------------------------------------------------------------------------
hourly = query("""select recorded_at, player_count from fact_player_activity
                  where steam_app_id = ? and data_resolution = 'hourly' and player_count is not null
                  order by recorded_at""", (app_id,))
if len(hourly) >= 24:
    hourly["recorded_at"] = pd.to_datetime(hourly["recorded_at"], utc=True).dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    # Break the line over collector outages instead of drawing a straight line across them
    gaps = hourly[hourly["recorded_at"].diff() > pd.Timedelta(hours=3)]
    breaks = pd.DataFrame({"recorded_at": gaps["recorded_at"] - pd.Timedelta(hours=1), "player_count": None})
    hourly = pd.concat([hourly, breaks]).sort_values("recorded_at")
    hx = alt.X("recorded_at:T", title=None, axis=alt.Axis(format="%d %b", tickCount="day"))
    hline = alt.Chart(hourly).mark_line(color=FLAT, strokeWidth=1.6).encode(
        x=hx, y=alt.Y("player_count:Q", title="Players online (hourly)", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("recorded_at:T", title="Time", format="%a %d %b, %H:%M"),
                 alt.Tooltip("player_count:Q", title="Players online", format=",.0f")])
    hlayers = [hline]
    month_avg = live.last_month_avg if live is not None else None
    if month_avg is not None and pd.notna(month_avg):
        ref = pd.DataFrame({"y": [month_avg], "label": [f"{live.last_month:%B} average"]})
        hlayers += [alt.Chart(ref).mark_rule(color=MUTED, strokeDash=[4, 3]).encode(y="y:Q"),
                    alt.Chart(ref).mark_text(align="left", x=4, dy=-7, color=INK_2, fontSize=11).encode(
                        y="y:Q", text="label:N")]
    hs = hourly.dropna().set_index("recorded_at")["player_count"]
    title = (f"Right now: {game} is {pct(live.vs_last_month, signed=True)} this week compared with its "
             f"{live.last_month:%B} average" if live is not None and pd.notna(live.vs_last_month)
             else f"{game}, hour by hour since {hs.index.min():%d %b}")
    chart_block(
        title,
        f"Players online every hour from the live pipeline, {hs.index.min():%d %b} – {hs.index.max():%d %b %Y, %H:%M} "
        "(Berlin time). The daily wave is day vs. night. The dashed line is the last complete month's average. "
        "Breaks in the line are hours when the collector wasn't running.",
        alt.layer(*hlayers).properties(height=240),
        "This is the most recent data in the dashboard. It picks up updates and events from this month, "
        "before they show up in the monthly history above.",
    )

# ---- Price history on Steam ---------------------------------------------------------------------
price = query("""select observed_at, price_amount, regular_amount, discount_pct, is_on_sale
                 from fact_price_snapshot where steam_app_id = ? and shop_id = 61 order by observed_at""", (app_id,))
if len(price) < 3:
    st.info(f"No Steam price history for {game}" + (" — it's free-to-play." if g.is_free else "."))
else:
    price["observed_at"] = pd.to_datetime(price["observed_at"]).dt.tz_localize(None)
    starts = int((price["is_on_sale"] & ~price["is_on_sale"].shift(fill_value=False)).sum())
    deepest = int(price["discount_pct"].max())
    step = alt.Chart(price).mark_line(interpolate="step-after", strokeWidth=1.2, color=INK).encode(
        x=alt.X("observed_at:T", title=None, axis=alt.Axis(format="%Y", tickCount="year")),
        y=alt.Y("price_amount:Q", title="Price on Steam (€)", scale=alt.Scale(zero=True)),
        tooltip=[alt.Tooltip("observed_at:T", title="Price changed on", format="%d %b %Y"),
                 alt.Tooltip("price_amount:Q", title="Price (€)", format=".2f"),
                 alt.Tooltip("regular_amount:Q", title="Normal price (€)", format=".2f"),
                 alt.Tooltip("discount_pct:Q", title="Discount %")])
    free_note = " It is free-to-play today." if g.is_free else ""
    chart_block(
        f"{game} has gone on sale {starts} times on Steam since {price.observed_at.min():%Y}; "
        f"the deepest discount was {deepest}% off",
        "The line is what the game cost on Steam over time. The flat top is its normal price; "
        "each dip down is a sale (deeper dip = bigger discount).",
        step.properties(height=260),
        "Sales are regular and predictable for most paid games: big Steam seasonal sales come round several times "
        "a year, so many buyers wait for them." + free_note,
    )

# ---- Player reviews by time played --------------------------------------------------------------
rev = query("""
    select case when playtime_at_review_minutes < 120 then 'Under 2 hours'
                when playtime_at_review_minutes < 600 then '2–10 hours'
                when playtime_at_review_minutes < 3000 then '10–50 hours'
                when playtime_at_review_minutes < 12000 then '50–200 hours'
                else '200+ hours' end as played,
           count(*) as reviews, avg(voted_up::int) as positive
    from fact_reviews where steam_app_id = ? group by 1
""", (app_id,))
BUCKETS = ["Under 2 hours", "2–10 hours", "10–50 hours", "50–200 hours", "200+ hours"]
rev = rev[rev["reviews"] >= 20]
if rev.empty:
    st.info(f"Not enough recent Steam reviews for {game} to break down.")
else:
    rv = rev.set_index("played").reindex([b for b in BUCKETS if b in set(rev["played"])])
    lo, hi = rv.iloc[0], rv.iloc[-1]
    bars = alt.Chart(rev).mark_bar(color=INK_2, cornerRadiusEnd=4, size=34).encode(
        x=alt.X("played:N", sort=BUCKETS, title="Time played when writing the review", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("positive:Q", title="Reviews that recommend the game", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip("played:N", title="Played"), alt.Tooltip("reviews:Q", title="Reviews"),
                 alt.Tooltip("positive:Q", title="Positive", format=".0%")])
    lbl = bars.mark_text(dy=-8, color=INK_2).encode(text=alt.Text("positive:Q", format=".0%"))
    direction = "more" if hi.positive > lo.positive + 0.05 else ("less" if hi.positive < lo.positive - 0.05 else "about as")
    chart_block(
        f"Players who put in the most hours are {direction} positive" + ("" if direction == "about as" else " than newcomers") +
        f": {hi.positive:.0%} of reviewers with {rv.index[-1].lower()} played recommend it, "
        f"vs. {lo.positive:.0%} of those with {rv.index[0].lower()}",
        f"Based on the {int(k.n_reviews):,} most recent Steam reviews. Each bar is the share of reviewers who "
        "recommend the game, grouped by how long they'd played when they wrote the review. Groups with fewer than 20 reviews are hidden.",
        (bars + lbl).properties(height=260),
        "Early reviews show first impressions; long-time players' reviews show whether the game holds up. "
        "A big gap between the two tells you which kind of game this is.",
    )

# ---- Critic reviews (OpenCritic subset) ---------------------------------------------------------
critic = query("""select outlet_name, raw_score, published_at from fact_critic_review
                  where steam_app_id = ? and score_base is not null order by raw_score""", (app_id,))
if critic.empty:
    st.caption("Critic reviews: not covered — OpenCritic data was collected for 12 of the 54 games only.")
else:
    dots = alt.Chart(critic).mark_point(filled=True, size=120, color=INK_2, opacity=0.8, stroke="white", strokeWidth=1).encode(
        x=alt.X("raw_score:Q", title="Critic score (out of 100)", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("outlet_name:N", title="Outlet"), alt.Tooltip("raw_score:Q", title="Score", format=".0f"),
                 alt.Tooltip("published_at:T", title="Published", format="%d %b %Y")])
    avg = alt.Chart(pd.DataFrame({"x": [critic["raw_score"].mean()]})).mark_rule(color=INK, strokeWidth=2).encode(x="x:Q")
    spread = critic["raw_score"].quantile(0.9) - critic["raw_score"].quantile(0.1)
    chart_block(
        f"Critics give {game} {critic['raw_score'].mean():.0f}/100 on average across {len(critic)} reviews"
        + (" — and they broadly agree" if spread <= 20 else " — but opinions are split"),
        "Each dot is one professional review (hover for the outlet); the black line is the average. "
        "All scores are converted to a 0–100 scale.",
        (dots + avg).properties(height=110),
        "Critics review a game once, usually at launch; player reviews above reflect the game as it is today.",
    )
