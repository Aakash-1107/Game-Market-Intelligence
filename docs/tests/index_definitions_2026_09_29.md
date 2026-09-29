# Index and percentage definitions — 2026-09-29 (updated after A3)

Every dashboard chart (and the tables and metrics that go with it) that shows a percentage or an index with a 100%
baseline, after the A3 index-consistency changes. The first version of this file (before A3, same date) is in git
history; section 2 lists what changed since then. All numbers come from the A3 build (`dbt build` 2026-09-29
17:57 UTC). Metric formulas are also in `docs/ANALYTICS.md`.

Charts with count axes only are not listed: the Overview genre bars, the Q2 class bars and the Q4 timeline.

## 1. Definitions

| # | Page — chart | Model.column(s) read | 100% = | How games are combined, and where | Games included / filters | Absolute baseline stored? |
|---|---|---|---|---|---|---|
| O1 | Market overview — "Which games gained or lost the most players this week?" (also the mover cards; same as **G2**) | `marts.fact_player_activity` (hourly), `marts.fact_player_activity_monthly`; ratio in dashboard SQL `common.live_snapshot()` | Each game's own average for the last complete month (Aug 2026): `activity_month = (select max(activity_month) …)`. Compared with the mean of hourly readings over the 7 days before the latest reading | Not combined; one bar per game. Top/bottom 6 picked in pandas | 53 games with hourly readings and an Aug 2026 month; 12 shown. The caption states both | Yes: `fact_player_activity_monthly.avg_players` |
| L1 | Q1 — "A typical game is down to 47% of its launch crowd after 3 months, then levels off at around 41%" | `reporting.rpt_lifecycle_curve.vs_launch_peak`; `reporting.rpt_lifecycle_typical_curve.median_vs_launch_peak, n_games, plateau_vs_launch_peak` | Launch peak = busiest month from the release month to 3 months later (`rpt_game_lifecycle.launch_peak_avg`) | **Median per month in SQL** (`rpt_lifecycle_typical_curve`). Plateau = median of the monthly medians for months 4–18, also in SQL | 42 settled games (≥ 1 year of history); 37–42 per month; thin lines: any of 50 launch-observed games | Yes: `launch_peak_avg` (also on every `rpt_lifecycle_curve` row) |
| L2 | Q1 — pattern bars (count axis) | `rpt_game_lifecycle.lifecycle_pattern` | Launch peak; classes on `m12_avg / launch_peak_avg` (< 30%, < 60%, ≤ 100%, above) | Counted per class in pandas | 50 games | Yes |
| L3 | Q1 — comebacks | `rpt_game_lifecycle.lowest_vs_launch_peak, latest_vs_launch_peak, lowest_after_launch_players, latest_avg_players, launch_peak_avg` | Launch peak | Not combined; one row per game | 13 games with `has_recovery` | **Yes (new):** `lowest_after_launch_players`; also `latest_avg_players`, `launch_peak_avg` |
| L4 | Q1 — table "All games" | `rpt_game_lifecycle.retention_m6/12/24, latest_vs_launch_peak` | Launch peak | Not combined | All 55 games | Yes: `m6_avg`, `m12_avg`, `m24_avg` |
| H2 | Q2 — scatter (y axis) | `rpt_activity_health.change_12m_pct, current_level_3m` | The game's own mean over the first 3 months of one global 12-month window (Sep–Nov 2025): `start_level_3m`; 0% on the axis = no change | Not combined; one dot per game | 46 judged games; y clipped at +150% (1 game) | Yes: `start_level_3m`, `current_level_3m` |
| H3 | Q2 — trend lines | `rpt_activity_health.start_level_3m`; `marts.fact_player_activity_monthly.avg_players`; ratio in dashboard SQL | Same `start_level_3m` | Not combined; one line per picked game | Any of 46 judged games | Yes: `start_level_3m` |
| S1 | Q3 — outcome bars (share of discounts) | `rpt_discount_effect.sale_outcome` | Share, not an index. Classes use S2's baseline (weeks 2–4 after vs. the 14 days before) | **Pooled across 174 discounts from 23 games** (pandas count share); the caption says so | `episode_status = 'valid'` and not confounded (147 valid episodes left out) | Yes: `baseline_avg` |
| S2 | Q3 — "A typical discount lifts players by 16%; 2–4 weeks after it ends, 6% extra are still playing" | `reporting.rpt_discount_typical.median_lift, n_discounts, n_games` | Each discount's own average daily players in the 14 days before it (`baseline_avg`) | **Median pooled across 174 discounts, in SQL** (`rpt_discount_typical`, group `all`; groups `75_or_more` and `under_50` feed the deep/light note) | As S1 | Yes: `rpt_discount_effect.baseline_avg` |
| S3 | Q3 — game detail "X: players rose during N of its M measurable discounts" | `reporting.rpt_discount_effect_daily.vs_baseline, avg_players, baseline_avg` | **That discount's own `baseline_avg` (14 days before), the same baseline as the side metric** | Not combined; one line per valid discount (14 days before to 28 days after); no smoothing | 23 pickable games; UTC days, complete 5-minute days | Yes: `baseline_avg` on every row |
| M1 | Q4 — "A sudden rush of players is about 13× more likely on a day with a big discount…" (share of days) | `rpt_market_anomalies.is_anomaly, direction, is_market_wide, sale_discount_pct, anomaly_status` | Share, not an index. Surge = z ≥ 3 against the previous 28 days' ln(players) | **Pooled across 21,715 game-days from 23 games** (pandas); the caption says so | Games ever discounted, scored days | **Yes (new):** `baseline_log_mean`, `baseline_log_stddev`, `baseline_players`, `band_lower_players`, `band_upper_players` |
| M3 | Q4 — game detail "Terraria's biggest moment: … 6.2× the level of the previous 28 days" | `rpt_market_anomalies.avg_players, baseline_players, band_lower_players, band_upper_players, z_score, is_anomaly` | No index on the chart: **absolute daily players (UTC)** with the detector's baseline and ±3 SD band. The headline and table ratio = `avg_players / baseline_players` | Not combined; one game | 29 pickable games | Yes (new columns, as M1) |
| G1 | Game explorer — monthly chart and "Busiest month ever" metric | `marts.fact_player_activity_monthly.avg_players` | **Chart and headline absolute.** "% of all-time peak" appears only as the metric's secondary line ("Aug 2026: 14% of it"), and the metric value is the peak (332,396) | Not combined | 53 games with monthly data | Peak computed in the page query (`max(avg_players)`) |
| G2 | Game explorer — "Players online now" delta | as O1 | as O1; the help text now shows the Aug 2026 value that is 100% | as O1 | as O1 | as O1 |
| G3 | Game explorer — reviews by playtime (share) | `fact_reviews.voted_up` | Share, not an index | Not combined | Buckets ≥ 20 reviews | — |

## 2. Changes since the first version (A3)

1. **UTC days everywhere.** The day-level detail charts no longer derive Berlin dates from 5-minute data. They read
   `rpt_discount_effect_daily` and `rpt_market_anomalies`, both built on `marts.fact_player_activity_daily`
   (UTC days). Axes are labelled "Date (UTC)". Hourly timestamps (live chart, "latest reading") are still shown
   in Berlin time and labelled so; they are clock times, not day definitions.
2. **Medians in SQL.** The Q1 typical curve (`rpt_lifecycle_typical_curve`) and the Q3 typical discount
   (`rpt_discount_typical`) reproduce the old pandas values exactly (difference 0.0 on every month and phase).
3. **Baselines stored.** Q4's z-score baseline and band, Q1's absolute lowest month, and Q3's per-discount baseline
   on every daily row. The rolling centred median ("typical level") is gone from the dashboard.
4. **One baseline per screen.**
   - Q3 detail uses the pre-discount baseline, like its side metric.
   - Q4 detail plots the baseline the detector used; the band reproduces the flags exactly: 375 flagged days =
     375 days outside the band, 0 disagreements.
   - Game explorer is absolute.
5. **Captions** state 100%, how games are combined, and N from data.
   - "1–4 weeks after" → "weeks 2–4 after".
   - Counts are derived: Q3 intro 14 → 23 games; Q4 21 → 29 games; Overview 54 → 55 (header and genre caption).
6. **Still in the dashboard (by design):** the O1 and H3 ratios (one stored column divided by another), the S1 and
   M1 pooled shares, and the Q3 side metric (median of one game's discounts).

## 3. Worked examples and baseline distributions

All SQL runs as-is on `data/game_market.duckdb` (A3 build).

### Counts used in the table

```sql
select 'O1 comparable games (vs_last_month not null)' as what, count(*) as n from (
  select g.steam_app_id
  from marts.dim_game g
  join (select distinct steam_app_id from marts.fact_player_activity
        where data_resolution = 'hourly' and player_count is not null) h using (steam_app_id)
  join marts.fact_player_activity_monthly m using (steam_app_id)
  where m.activity_month = (select max(activity_month) from marts.fact_player_activity_monthly) and m.avg_players <> 0)
union all select 'L1 settled games (launch_observed, pattern <> insufficient_history)', count(*) from reporting.rpt_game_lifecycle
  where lifecycle_status = 'launch_observed' and lifecycle_pattern <> 'insufficient_history'
union all select 'L1 all launch_observed games (curves query)', count(*) from reporting.rpt_game_lifecycle
  where lifecycle_status = 'launch_observed'
union all select 'L2 games with a pattern', count(*) from reporting.rpt_game_lifecycle where lifecycle_pattern is not null
union all select 'L3 comeback games (has_recovery)', count(*) from reporting.rpt_game_lifecycle where has_recovery
union all select 'H1 games (all dim_game)', count(*) from reporting.rpt_activity_health
union all select 'H2 scatter games (judged, non-null level and change)', count(*) from reporting.rpt_activity_health
  where health_class in ('declining','growing','stable','volatile') and current_level_3m is not null and change_12m_pct is not null
union all select 'H2 of which clipped at +150%', count(*) from reporting.rpt_activity_health
  where health_class in ('declining','growing','stable','volatile') and change_12m_pct > 1.5
union all select 'H3 pickable games (judged)', count(*) from reporting.rpt_activity_health
  where health_class in ('declining','growing','stable','volatile')
union all select 'S1/S2 clean episodes (valid, not confounded)', count(*) from reporting.rpt_discount_effect
  where episode_status = 'valid' and not post_window_confounded
union all select 'S1/S2 games behind clean episodes', count(distinct steam_app_id) from reporting.rpt_discount_effect
  where episode_status = 'valid' and not post_window_confounded
union all select 'S1 valid episodes left out as confounded', count(*) from reporting.rpt_discount_effect
  where episode_status = 'valid' and post_window_confounded
union all select 'S3 pickable games (>=1 valid episode)', count(distinct steam_app_id) from reporting.rpt_discount_effect
  where episode_status = 'valid'
union all select 'M1 paid games (scored days, ever during_sale)', count(distinct steam_app_id) from reporting.rpt_market_anomalies
  where anomaly_status = 'scored' and steam_app_id in (select steam_app_id from reporting.rpt_market_anomalies where during_sale)
union all select 'M1 scored days of paid games', count(*) from reporting.rpt_market_anomalies
  where anomaly_status = 'scored' and steam_app_id in (select steam_app_id from reporting.rpt_market_anomalies where during_sale)
union all select 'M3 pickable games (any row in rpt_market_anomalies)', count(distinct steam_app_id) from reporting.rpt_market_anomalies
union all select 'G1 games with monthly data', count(distinct steam_app_id) from marts.fact_player_activity_monthly
```

Result:

| what | n |
|---|---|
| O1 comparable games (vs_last_month not null) | 53 |
| L1 settled games (launch_observed, pattern <> insufficient_history) | 42 |
| L1 all launch_observed games (curves query) | 50 |
| L2 games with a pattern | 50 |
| L3 comeback games (has_recovery) | 13 |
| H1 games (all dim_game) | 55 |
| H2 scatter games (judged, non-null level and change) | 46 |
| H2 of which clipped at +150% | 1 |
| H3 pickable games (judged) | 46 |
| S1/S2 clean episodes (valid, not confounded) | 174 |
| S1/S2 games behind clean episodes | 23 |
| S1 valid episodes left out as confounded | 147 |
| S3 pickable games (>=1 valid episode) | 23 |
| M1 paid games (scored days, ever during_sale) | 23 |
| M1 scored days of paid games | 21715 |
| M3 pickable games (any row in rpt_market_anomalies) | 29 |
| G1 games with monthly data | 53 |

### O1 / G2 — last 7 days vs. last complete month

Cyberpunk 2077: August 2026 = 45,728 (100%); last 7 days = 27,188 → **−40.5%**.

```sql
with hourly as (
    select steam_app_id, player_count, recorded_at
    from marts.fact_player_activity
    where data_resolution = 'hourly' and player_count is not null
),
last_reading as (select max(recorded_at) as t from hourly),
per_game as (
    select h.steam_app_id,
           avg(h.player_count) filter (where h.recorded_at > l.t - interval 7 day) as avg_7d,
           count(*)            filter (where h.recorded_at > l.t - interval 7 day) as readings_7d
    from hourly h cross join last_reading l
    group by h.steam_app_id
),
last_month as (
    select steam_app_id, activity_month as baseline_month, avg_players as baseline
    from marts.fact_player_activity_monthly
    where activity_month = (select max(activity_month) from marts.fact_player_activity_monthly)
),
b as (
    select g.steam_app_id, g.name, m.baseline_month, m.baseline, p.avg_7d, p.readings_7d,
           p.avg_7d / nullif(m.baseline, 0) - 1 as vs_last_month, (select t from last_reading) as last_reading
    from marts.dim_game g
    join per_game p using (steam_app_id)
    left join last_month m using (steam_app_id)
)
select name, baseline_month, round(baseline, 1) as baseline, round(avg_7d, 1) as avg_7d, readings_7d,
       round(vs_last_month, 4) as vs_last_month, last_reading
from b where steam_app_id = 1091500   -- Cyberpunk 2077
```

Result:

| name | baseline_month | baseline | avg_7d | readings_7d | vs_last_month | last_reading |
|---|---|---|---|---|---|---|
| Cyberpunk 2077 | 2026-08-01 00:00:00 | 45728.0 | 27192.7 | 169 | -0.4053 | 2026-09-29 19:00:57.295437+02:00 |

```sql
with hourly as (
    select steam_app_id, player_count, recorded_at
    from marts.fact_player_activity
    where data_resolution = 'hourly' and player_count is not null
),
last_reading as (select max(recorded_at) as t from hourly),
per_game as (
    select h.steam_app_id,
           avg(h.player_count) filter (where h.recorded_at > l.t - interval 7 day) as avg_7d,
           count(*)            filter (where h.recorded_at > l.t - interval 7 day) as readings_7d
    from hourly h cross join last_reading l
    group by h.steam_app_id
),
last_month as (
    select steam_app_id, activity_month as baseline_month, avg_players as baseline
    from marts.fact_player_activity_monthly
    where activity_month = (select max(activity_month) from marts.fact_player_activity_monthly)
),
b as (
    select g.steam_app_id, g.name, m.baseline_month, m.baseline, p.avg_7d, p.readings_7d,
           p.avg_7d / nullif(m.baseline, 0) - 1 as vs_last_month, (select t from last_reading) as last_reading
    from marts.dim_game g
    join per_game p using (steam_app_id)
    left join last_month m using (steam_app_id)
)
select count(*) as n, round(min(baseline), 1) as min, arg_min(name, baseline) as min_game,
       round(median(baseline), 1) as median, round(max(baseline), 1) as max, arg_max(name, baseline) as max_game
from b where vs_last_month is not null
```

Result:

| n | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 53 | 2295.6 | Dead Cells | 28638.2 | 825257.8 | Counter-Strike 2 |

### L1 — % of launch peak and the typical curve

Cyberpunk 2077: launch peak Dec 2020 = 332,396 (100%). Month 3 = **4.0%**, month 12 = 5.0%, month 24 = 8.5%.

```sql
select name, launch_peak_avg, month_index, activity_month, round(avg_players, 1) as avg_players,
       round(vs_launch_peak, 4) as vs_launch_peak
from reporting.rpt_lifecycle_curve
where steam_app_id = 1091500   -- Cyberpunk 2077
  and month_index in (0, 1, 2, 3, 12, 24)
order by month_index
```

Result:

| name | launch_peak_avg | month_index | activity_month | avg_players | vs_launch_peak |
|---|---|---|---|---|---|
| Cyberpunk 2077 | 332395.65 | 0 | 2020-12-01 00:00:00 | 332395.7 | 1.0 |
| Cyberpunk 2077 | 332395.65 | 1 | 2021-01-01 00:00:00 | 82146.7 | 0.2471 |
| Cyberpunk 2077 | 332395.65 | 2 | 2021-02-01 00:00:00 | 24704.8 | 0.0743 |
| Cyberpunk 2077 | 332395.65 | 3 | 2021-03-01 00:00:00 | 13145.8 | 0.0395 |
| Cyberpunk 2077 | 332395.65 | 12 | 2021-12-01 00:00:00 | 16773.7 | 0.0505 |
| Cyberpunk 2077 | 332395.65 | 24 | 2022-12-01 00:00:00 | 28087.9 | 0.0845 |

The typical line, as stored:

```sql
-- the black line, read as-is by the dashboard
select month_index, round(median_vs_launch_peak, 4) as median_vs_launch_peak, n_games,
       round(plateau_vs_launch_peak, 4) as plateau_vs_launch_peak, n_games_total
from reporting.rpt_lifecycle_typical_curve
where month_index in (0, 3, 6, 12, 18, 24)
order by month_index
```

Result:

| month_index | median_vs_launch_peak | n_games | plateau_vs_launch_peak | n_games_total |
|---|---|---|---|---|
| 0 | 1.0 | 40 | 0.4144 | 42 |
| 3 | 0.473 | 42 | 0.4144 | 42 |
| 6 | 0.3884 | 42 | 0.4144 | 42 |
| 12 | 0.6078 | 42 | 0.4144 | 42 |
| 18 | 0.4203 | 40 | 0.4144 | 42 |
| 24 | 0.6118 | 37 | 0.4144 | 42 |

```sql
select count(*) as n, round(min(launch_peak_avg), 1) as min, arg_min(name, launch_peak_avg) as min_game,
       round(median(launch_peak_avg), 1) as median, round(max(launch_peak_avg), 1) as max,
       arg_max(name, launch_peak_avg) as max_game
from reporting.rpt_game_lifecycle
where lifecycle_status = 'launch_observed' and lifecycle_pattern <> 'insufficient_history'
```

Result:

| n | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 42 | 3577.8 | FINAL FANTASY XIV Online | 28476.7 | 1584886.8 | PUBG: BATTLEGROUNDS |

### L3 — comebacks

No Man's Sky: launch peak 36,976 (100%). Lowest month after it = **508 players (1.4%)**, now a stored column.
Aug 2026 = 8,244 (22.3%).

```sql
select name, round(launch_peak_avg, 1) as launch_peak_avg, launch_peak_month_index,
       round(lowest_after_launch_players, 1) as lowest_after_launch_players,   -- stored since A3
       round(lowest_vs_launch_peak, 4) as lowest_vs_launch_peak,
       last_month, round(latest_avg_players, 1) as latest_avg_players,
       round(latest_vs_launch_peak, 4) as latest_vs_launch_peak, first_recovery_month_index
from reporting.rpt_game_lifecycle
where steam_app_id = 275850   -- No Man's Sky
```

Result:

| name | launch_peak_avg | launch_peak_month_index | lowest_after_launch_players | lowest_vs_launch_peak | last_month | latest_avg_players | latest_vs_launch_peak | first_recovery_month_index |
|---|---|---|---|---|---|---|---|---|
| No Man's Sky | 36976.4 | 0 | 508.0 | 0.0137 | 2026-08-01 00:00:00 | 8244.4 | 0.223 | 111 |

```sql
select count(*) as n, round(min(launch_peak_avg), 1) as min, arg_min(name, launch_peak_avg) as min_game,
       round(median(launch_peak_avg), 1) as median, round(max(launch_peak_avg), 1) as max,
       arg_max(name, launch_peak_avg) as max_game
from reporting.rpt_game_lifecycle
where has_recovery
```

Result:

| n | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 13 | 4437.7 | Dead Cells | 26184.6 | 75294.1 | Grand Theft Auto V Enhanced |

### H2 / H3 — vs. start of the 12-month window

Cyberpunk 2077: start level (Sep–Nov 2025) = 30,228 (100%). Aug 2026 = 45,728 = **151%**; change over 12 months
= **+47.8%**.

```sql
select h.name, h.window_start, h.window_end, round(h.start_level_3m, 1) as start_level_3m,
       round(h.current_level_3m, 1) as current_level_3m, round(h.change_12m_pct, 4) as change_12m_pct,
       m.activity_month, round(m.avg_players, 1) as avg_players,
       round(m.avg_players / h.start_level_3m, 4) as vs_start
from reporting.rpt_activity_health h
join marts.fact_player_activity_monthly m
  on m.steam_app_id = h.steam_app_id and m.activity_month between h.window_start and h.window_end
where h.steam_app_id = 1091500   -- Cyberpunk 2077
order by m.activity_month
```

Result:

| name | window_start | window_end | start_level_3m | current_level_3m | change_12m_pct | activity_month | avg_players | vs_start |
|---|---|---|---|---|---|---|---|---|
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2025-09-01 00:00:00 | 32970.2 | 1.0907 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2025-10-01 00:00:00 | 31692.3 | 1.0485 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2025-11-01 00:00:00 | 26020.7 | 0.8608 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2025-12-01 00:00:00 | 38704.3 | 1.2804 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-01-01 00:00:00 | 37310.1 | 1.2343 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-02-01 00:00:00 | 28195.9 | 0.9328 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-03-01 00:00:00 | 26846.1 | 0.8881 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-04-01 00:00:00 | 27491.0 | 0.9095 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-05-01 00:00:00 | 27605.4 | 0.9132 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-06-01 00:00:00 | 34392.0 | 1.1378 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-07-01 00:00:00 | 53894.7 | 1.783 |
| Cyberpunk 2077 | 2025-09-01 00:00:00 | 2026-08-01 00:00:00 | 30227.7 | 44671.5 | 0.4778 | 2026-08-01 00:00:00 | 45728.0 | 1.5128 |

```sql
select count(*) as n, round(min(start_level_3m), 1) as min, arg_min(name, start_level_3m) as min_game,
       round(median(start_level_3m), 1) as median, round(max(start_level_3m), 1) as max,
       arg_max(name, start_level_3m) as max_game
from reporting.rpt_activity_health
where health_class in ('declining', 'growing', 'stable', 'volatile')
  and current_level_3m is not null and change_12m_pct is not null
```

Result:

| n | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 46 | 2080.5 | Dead Cells | 26311.2 | 951889.0 | Counter-Strike 2 |

### S1 / S2 — vs. the 14 days before a discount

No Man's Sky, 2019-03-25 to 2019-03-31: baseline 1,720 (100%), during 3,033 → **+76.4%**; weeks 2–4 after →
+46.7%.

```sql
select name, sale_start, sale_end, max_discount_pct, baseline_days, round(baseline_avg, 1) as baseline_avg,
       round(during_avg, 1) as during_avg, round(lift_during, 4) as lift_during,
       round(post_early_avg, 1) as post_early_avg, round(lift_post_early, 4) as lift_post_early,
       round(post_late_avg, 1) as post_late_avg, round(lift_post_late, 4) as lift_post_late
from reporting.rpt_discount_effect
where steam_app_id = 275850   -- No Man's Sky
  and episode_status = 'valid' and not post_window_confounded
order by sale_start
```

Result:

| name | sale_start | sale_end | max_discount_pct | baseline_days | baseline_avg | during_avg | lift_during | post_early_avg | lift_post_early | post_late_avg | lift_post_late |
|---|---|---|---|---|---|---|---|---|---|---|---|
| No Man's Sky | 2018-02-16 00:00:00 | 2018-02-18 00:00:00 | 60 | 12 | 660.1 | 821.3 | 0.2443 | 748.4 | 0.1337 | 583.4 | -0.1162 |
| No Man's Sky | 2018-07-24 00:00:00 | 2018-08-05 00:00:00 | 50 | 14 | 1857.8 | 54594.6 | 28.3872 | 39453.8 | 20.2372 | 15613.4 | 7.4044 |
| No Man's Sky | 2019-02-04 00:00:00 | 2019-02-10 00:00:00 | 50 | 14 | 2413.4 | 2553.8 | 0.0582 | 2483.2 | 0.0289 | 1852.0 | -0.2326 |
| No Man's Sky | 2019-03-25 00:00:00 | 2019-03-31 00:00:00 | 50 | 13 | 1719.9 | 3033.1 | 0.7635 | 3250.0 | 0.8896 | 2523.5 | 0.4672 |
| No Man's Sky | 2019-05-16 00:00:00 | 2019-05-19 00:00:00 | 50 | 14 | 2280.1 | 3813.1 | 0.6724 | 3874.8 | 0.6994 | 2921.7 | 0.2814 |
| No Man's Sky | 2019-08-07 00:00:00 | 2019-08-25 00:00:00 | 50 | 14 | 3288.3 | 22889.0 | 5.9608 | 20369.6 | 5.1946 | 9525.7 | 1.8969 |
| No Man's Sky | 2020-02-17 00:00:00 | 2020-02-23 00:00:00 | 50 | 14 | 4329.5 | 8497.4 | 0.9627 | 10301.4 | 1.3794 | 6192.0 | 0.4302 |
| No Man's Sky | 2020-04-01 00:00:00 | 2020-04-12 00:00:00 | 50 | 14 | 5027.8 | 10717.8 | 1.1317 | 15762.9 | 2.1351 | 8745.0 | 0.7393 |

The typical discount, as stored:

```sql
-- the line and the deep/light note, read as-is by the dashboard
select discount_group, phase, round(1 + median_lift, 4) as level, n_discounts, n_games
from reporting.rpt_discount_typical
order by discount_group, phase_order
```

Result:

| discount_group | phase | level | n_discounts | n_games |
|---|---|---|---|---|
| 75_or_more | before | 1.0 | 36 | 8 |
| 75_or_more | during | 1.2025 | 36 | 8 |
| 75_or_more | first_week_after | 1.2309 | 36 | 8 |
| 75_or_more | weeks_2_4_after | 1.063 | 36 | 8 |
| all | before | 1.0 | 174 | 23 |
| all | during | 1.1563 | 174 | 23 |
| all | first_week_after | 1.1717 | 174 | 23 |
| all | weeks_2_4_after | 1.0644 | 174 | 23 |
| under_50 | before | 1.0 | 52 | 12 |
| under_50 | during | 1.1528 | 52 | 12 |
| under_50 | first_week_after | 1.1815 | 52 | 12 |
| under_50 | weeks_2_4_after | 1.0607 | 52 | 12 |

```sql
select count(*) as n_episodes, round(min(baseline_avg), 1) as min, arg_min(name, baseline_avg) as min_game,
       round(median(baseline_avg), 1) as median, round(max(baseline_avg), 1) as max,
       arg_max(name, baseline_avg) as max_game
from reporting.rpt_discount_effect
where episode_status = 'valid' and not post_window_confounded
```

Result:

| n_episodes | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 174 | 660.1 | No Man's Sky | 11499.9 | 811690.4 | PUBG: BATTLEGROUNDS |

```sql
-- per game: median baseline over its clean episodes, then the spread across games
with per_game as (
    select name, median(baseline_avg) as baseline, count(*) as episodes
    from reporting.rpt_discount_effect
    where episode_status = 'valid' and not post_window_confounded
    group by name
)
select count(*) as n_games, round(min(baseline), 1) as min, arg_min(name, baseline) as min_game,
       round(median(baseline), 1) as median, round(max(baseline), 1) as max, arg_max(name, baseline) as max_game
from per_game
```

Result:

| n_games | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 23 | 1344.0 | Dead Cells | 11277.3 | 337457.0 | PUBG: BATTLEGROUNDS |

### S3 — Q3 detail, same baseline as the side metric

Terraria, discount 2018-12-20 to 2019-01-06 (50% off): baseline = 14,843 players (the 14 days before) = 100%. On
2018-12-28 (UTC) there were 23,522 players = **158.5%**. The line's average over the 18 discount days = **+56.1029%**,
the same as `lift_during`, which is the per-discount value behind the side metric. Before A3 the same day read
108.6% (106.5% smoothed) against a different baseline.

```sql
-- Q3 detail, Terraria discount 2018-12-20 .. 2019-01-06: the line (vs_baseline) averages exactly to lift_during
select e.sale_start, e.sale_end, e.max_discount_pct, e.baseline_days, round(e.baseline_avg, 1) as baseline_avg,
       round(e.lift_during, 6) as lift_during_metric,
       round(avg(d.vs_baseline) filter (where d.phase = 'during') - 1, 6) as line_mean_during_minus_1,
       max(d.vs_baseline) filter (where d.activity_date = date '2018-12-28') as line_on_2018_12_28,
       max(d.avg_players) filter (where d.activity_date = date '2018-12-28') as players_on_2018_12_28
from reporting.rpt_discount_effect e
join reporting.rpt_discount_effect_daily d using (sale_episode_key)
where e.steam_app_id = 105600 and e.sale_start = date '2018-12-20'
group by all
```

Result:

| sale_start | sale_end | max_discount_pct | baseline_days | baseline_avg | lift_during_metric | line_mean_during_minus_1 | line_on_2018_12_28 | players_on_2018_12_28 |
|---|---|---|---|---|---|---|---|---|
| 2018-12-20 00:00:00 | 2019-01-06 00:00:00 | 50 | 14 | 14843.4 | 0.561029 | 0.561029 | 1.5846487658933304 | 23521.559027777777 |

Baseline distribution (per game: median `baseline_avg` of its valid discounts):

```sql
-- the chart's 100% = baseline_avg of each valid episode (the episodes drawn as lines); per game median, 23 games
with per_game as (
    select g.name, median(e.baseline_avg) as baseline
    from reporting.rpt_discount_effect e join marts.dim_game g using (steam_app_id)
    where e.episode_status = 'valid'
    group by g.name
)
select count(*) as n_games, round(min(baseline), 1) as min, arg_min(name, baseline) as min_game,
       round(median(baseline), 1) as median, round(max(baseline), 1) as max, arg_max(name, baseline) as max_game
from per_game
```

Result:

| n_games | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 23 | 1328.7 | Dead Cells | 11266.0 | 317103.0 | Counter-Strike 2 |

### M3 — Q4 detail, the detector's own baseline

Terraria, 2020-05-17 (Journey's End):
- The previous 28 days' baseline = 50,348 players; normal range 24,657–102,808.
- The day had 313,955 players = **6.24×** the baseline (z = +7.69), so it is flagged.
- Before A3 the headline said 4.6× against the centred ±30-day median, which included the update's own weeks.

```sql
-- Q4 detail, Terraria 2020: the flagged day furthest from its 28-day baseline (the page headline)
select activity_date, direction, round(z_score, 2) as z_score, baseline_days,
       round(avg_players, 1) as avg_players, round(baseline_players, 1) as baseline_players,
       round(band_lower_players, 1) as band_lower, round(band_upper_players, 1) as band_upper,
       round(avg_players / baseline_players, 4) as vs_baseline
from reporting.rpt_market_anomalies
where steam_app_id = 105600 and is_anomaly and year(activity_date) = 2020
order by abs(ln(avg_players / baseline_players)) desc
limit 1
```

Result:

| activity_date | direction | z_score | baseline_days | avg_players | baseline_players | band_lower | band_upper | vs_baseline |
|---|---|---|---|---|---|---|---|---|
| 2020-05-17 00:00:00 | spike | 7.69 | 28 | 313955.4 | 50348.0 | 24657.0 | 102807.6 | 6.2357 |

Baseline distribution (per game: median `baseline_players` over its scored days):

```sql
-- the chart's baseline = baseline_players (geometric mean of the previous 28 days); per game median over scored days
with per_game as (
    select g.name, median(a.baseline_players) as baseline
    from reporting.rpt_market_anomalies a join marts.dim_game g using (steam_app_id)
    where a.anomaly_status = 'scored'
    group by g.name
)
select count(*) as n_games, round(min(baseline), 1) as min, arg_min(name, baseline) as min_game,
       round(median(baseline), 1) as median, round(max(baseline), 1) as max, arg_max(name, baseline) as max_game
from per_game
```

Result:

| n_games | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 29 | 1586.0 | Dead Cells | 12428.3 | 455031.5 | Dota 2 |

### G1 — busiest month (metric only)

Cyberpunk 2077: busiest month Dec 2020 = 332,396 (the metric's value); Aug 2026 = 45,728, shown as the secondary line
"Aug 2026: 14% of it". The chart and its headline are absolute.

```sql
select name, arg_max(activity_month, avg_players) as peak_month, round(max(avg_players), 1) as peak_avg,
       max(activity_month) as latest_month, round(arg_max(avg_players, activity_month), 1) as latest_avg,
       round(arg_max(avg_players, activity_month) / max(avg_players), 4) as share_now
from marts.fact_player_activity_monthly m join marts.dim_game g using (steam_app_id)
where steam_app_id = 1091500   -- Cyberpunk 2077
group by name
```

Result:

| name | peak_month | peak_avg | latest_month | latest_avg | share_now |
|---|---|---|---|---|---|
| Cyberpunk 2077 | 2020-12-01 00:00:00 | 332395.7 | 2026-08-01 00:00:00 | 45728.0 | 0.1376 |

```sql
with per_game as (
    select g.name, max(m.avg_players) as peak
    from marts.fact_player_activity_monthly m join marts.dim_game g using (steam_app_id)
    group by g.name
)
select count(*) as n, round(min(peak), 1) as min, arg_min(name, peak) as min_game,
       round(median(peak), 1) as median, round(max(peak), 1) as max, arg_max(name, peak) as max_game
from per_game
```

Result:

| n | min | min_game | median | max | max_game |
|---|---|---|---|---|---|
| 53 | 7020.9 | Dead Cells | 80779.9 | 1584886.8 | PUBG: BATTLEGROUNDS |
