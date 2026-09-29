import pandas as pd
import streamlit as st

from common import STEAM_ATTRIBUTION, coverage, local, page_header, pipeline_counts
from db import query

cov = coverage()
k = pipeline_counts()
live_last = local(cov.live_last)
page_header(
    "How the data is built",
    "Where every number in this dashboard comes from, how it gets here, how fresh it is, "
    "and what it doesn't cover.",
)

c = query("""
    select
        (select count(distinct steam_app_id) from marts.fact_player_activity where data_resolution = 'hourly') as live_games,
        (select count(distinct steam_app_id) from marts.fact_player_activity_monthly)                    as monthly_games,
        (select count(*) from marts.fact_player_activity_monthly)                                        as monthly_rows,
        (select count(distinct steam_app_id) from marts.fact_player_activity where data_resolution = '5min') as fine_games,
        (select count(distinct steam_app_id) from marts.fact_price_snapshot)                             as price_games,
        (select min(observed_at) from marts.fact_price_snapshot)                                         as price_first,
        (select count(distinct steam_app_id) from marts.fact_reviews)                                    as review_games,
        (select count(*) from reporting.rpt_discount_effect)                                             as sale_periods,
        (select count(*) from reporting.rpt_market_anomalies)                                            as days_checked
""").iloc[0]
missing = query("""
    select string_agg(name, ', ' order by name) filter (where steam_app_id not in
               (select steam_app_id from marts.fact_player_activity_monthly))            as no_monthly,
           string_agg(name, ', ' order by name) filter (where steam_app_id not in
               (select steam_app_id from marts.fact_price_snapshot))                     as no_prices
    from marts.dim_game
""").iloc[0]

# ---- What we collect ----------------------------------------------------------------------------
st.markdown("#### What we collect")
st.markdown(f"""
| Data | Source | How often | Games | Covers |
|---|---|---|---|---|
| Players online, live | Steam Web API | Every hour, automatically | {c.live_games} | {local(cov.live_first):%d %b %Y} – {live_last:%d %b %Y, %H:%M} |
| Players online, monthly average | SteamCharts, gaps filled from a Kaggle archive | Refreshed by hand | {c.monthly_games} | {cov.monthly_first:%b %Y} – {cov.monthly_last:%b %Y} |
| Players online, every 5 minutes | Historical backfill (one-off import) | Once | {c.fine_games} | {local(cov.fine_first):%b %Y} – {local(cov.fine_last):%b %Y} |
| Prices and discounts | IsThereAnyDeal price history (Steam and {k.shops - 1} other shops) | Refreshed by hand | {c.price_games} | {local(c.price_first):%Y} – today |
| Player reviews | Steam reviews (the 1,000 most recent per game) | Refreshed by hand | {c.review_games} | Most recent reviews |
| Game details | Steam store (name, genres, release date, free or paid) | Refreshed by hand | {k.games} | Current store page |
""")
st.caption(f"The {k.games} games were picked by hand: popular PC games on Steam, "
           f"{k.free_games} of them free-to-play. {STEAM_ATTRIBUTION}")

# ---- How it gets here ---------------------------------------------------------------------------
st.markdown("#### How it gets here")
st.markdown("""
1. **Collect.** Python scripts call each source. The live player count runs every hour on a schedule (Prefect);
   the other sources are refreshed by hand when needed.
2. **Store the raw files.** Every response is saved unchanged (Parquet, JSON or CSV) in cloud storage (AWS S3),
   sorted by source and date. Nothing is edited at this stage, so every later step can be rebuilt from scratch.
3. **Clean and combine (dbt).** dbt loads the raw files into a DuckDB database in three layers: *staging* cleans
   each source, *intermediate* builds daily player counts and discount periods, and *marts* hold the final tables,
   including one table per question this dashboard answers.
4. **Show.** This dashboard reads those final tables. It never changes them.
""")

# ---- Pipeline scale -----------------------------------------------------------------------------
st.markdown("#### Pipeline scale")
st.table(
    pd.DataFrame([
        ("Player-count readings (live hourly + 5-minute backfill)", "fact_player_activity", k.readings),
        ("Monthly player averages", "fact_player_activity_monthly", c.monthly_rows),
        ("Price changes", "fact_price_snapshot", k.price_changes),
        ("Player reviews", "fact_reviews", k.reviews),
        ("Discount periods measured (page: Do discounts bring players?)", "rpt_discount_effect", c.sale_periods),
        ("Game-days checked for unusual activity (page: Unusual days)", "rpt_market_anomalies", c.days_checked),
    ], columns=["What", "Table", "Rows"]).assign(Rows=lambda d: d["Rows"].map(lambda n: f"{n:,}")),
    hide_index=True,
)

# ---- How fresh it is ----------------------------------------------------------------------------
st.markdown("#### How fresh it is")
st.markdown(
    f"- **Last live reading:** {live_last:%a %d %b %Y, %H:%M} (Berlin time).\n"
    f"- **Last complete month:** {cov.monthly_last:%B %Y}. Pages built on monthly data stop there; newer activity is "
    "on the Market overview.\n"
    "- New live readings are collected every hour, but reach this dashboard only after the next dbt build.\n"
    "- The dashboard loads the data once and keeps it until it is restarted, so numbers never change in the middle "
    "of a presentation. Restart it to see new data."
)

# ---- Known gaps ---------------------------------------------------------------------------------
gap = (f"- **Live collector outage:** no hourly readings from {local(cov.live_gap_start):%d %b %H:%M} to "
       f"{local(cov.live_gap_end):%d %b %H:%M}. Charts show a break in the line there.\n"
       if pd.notna(cov.live_gap_start) else "")
st.markdown("#### Known gaps")
st.markdown(
    gap
    + f"- **Day-by-day history is old and partial:** the 5-minute data covers only {c.fine_games} games, "
      f"{local(cov.fine_first):%b %Y} – {local(cov.fine_last):%b %Y}. After that, history exists only as monthly "
      "averages, which are too coarse to see a single discount or an unusual day. That's why *Do discounts bring players?* "
      "and *Unusual days* use this period.\n"
    + f"- **Monthly history:** {c.monthly_games} of {k.games} games"
    + (f"; missing: {missing.no_monthly} (released too recently for a complete month).\n" if missing.no_monthly else ".\n")
    + f"- **Prices:** {c.price_games} of {k.games} games have a price history"
    + (f"; missing: {missing.no_prices}.\n" if missing.no_prices else ".\n")
    + "- **Reviews** are the most recent 1,000 per game, not every review ever written.\n"
    + "- **Dying Light** was dropped from the list because the Steam store returns no details for it, "
      f"so the dashboard follows {k.games} games."
)
