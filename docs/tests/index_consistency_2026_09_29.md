# Index consistency (A3) — 2026-09-29

Goal: one day definition (UTC), medians computed in SQL, baselines stored in the reporting models, one baseline per
screen, and captions that state what 100% is, how games are combined, and N. Headline figures had to stay identical.
**They did.** Metric definitions: `docs/ANALYTICS.md`. Updated per-chart audit: `index_definitions_2026_09_29.md`.

## Verification

- **Build:** `dbt build` gave `PASS=192 WARN=0 ERROR=0` (199 nodes). That is A2's 178 + 4 new models + 10 new tests.
- **Fingerprints:** `fingerprints/fingerprint_pre_index_2026_09_29.*` vs `fingerprints/fingerprint_post_index_2026_09_29.*`.
  - Both runs use `--cutoff "2026-09-29 17:17:48+00"` (the A2 build start), so hourly data landing during A3
    doesn't count.
  - `game_coverage.hourly_rows` / `last_hourly_at` are left out of both runs: they read the staging view with no
    cutoff.
  - **Every existing relation is identical.** For `rpt_game_lifecycle` and `rpt_market_anomalies` that covers all
    columns that existed before; the new columns are left out with `--drop-columns`.
  - The only differences are the 4 new models: `rpt_lifecycle_curve` (1,068 rows), `rpt_lifecycle_typical_curve`
    (25), `rpt_discount_typical` (12) and `rpt_discount_effect_daily` (16,001).
- **Fingerprint tool changes:**
  - DATE cutoff columns are now cut at the cutoff's UTC date (complete days only). A date compared with a
    mid-day timestamp would otherwise keep a day that is still collecting hourly readings. Midnight cutoffs give
    the same result as before.
  - New option `--drop-columns table.col`.
  - The diff compares rows and fingerprint only.
- **Medians in SQL vs. the old pandas code:** the difference is 0.0 on all 25 months of the typical curve, on the
  plateau, and on every phase and group of the typical discount.
- **Dashboard:** all 7 pages render with no errors (the Overview `page_link` exception is the known `AppTest`
  artefact, the same as before).

## Headline figures before / after

"Before" is the A2 dashboard logic (pandas) on the A2 tables. "After" is the new reporting models and the
rendered pages.

| Headline | Before | After |
|---|---|---|
| Q1 typical game at month 3 | 47.30% (0.4730006406) | 47.30% (0.4730006406), from `rpt_lifecycle_typical_curve` |
| Q1 plateau (months 4–18) | 41.44% (0.4144120404) | 41.44% (0.4144120404) |
| Q1 settled games / patterns / comebacks | 42 / 15-5-12-8-10 / 13 (4 above launch) | identical |
| Q2 classes (stable, volatile, growing, declining, too recent, no data) | 30, 11, 3, 2, 7, 2; declining = Hades, No Man's Sky | identical; `change_12m_pct` identical for all 49 games that have one |
| Q3 typical discount: during / first week / weeks 2–4 | 115.63% / 117.17% / 106.44% (174 discounts, 23 games) | identical, from `rpt_discount_typical` |
| Q3 outcome bars (stayed higher / back to normal / no bump / fell below) | 72 / 58 / 34 / 10 of 174 (41.4% / 33.3% / 19.5% / 5.7%) | identical |
| Q3 deep vs. light discounts (during; weeks 2–4) | +20.3% vs +15.3%; +6.3% vs +6.1% | identical |
| Q4 surges / drops / Steam-wide days | 255 / 57 / 18 | identical |
| Q4 surge ratio | 13.38× (rendered "13×") | identical |

Changed on purpose (not headline figures):
- **Q4 Terraria detail headline:** "4.6× the usual level" → "6.2× the level of the previous 28 days" (new baseline).
- **Game explorer headline:** "…it had 14% of that" → "…it had about 45,728". The 14% moved into the "Busiest month
  ever" metric.
- **Derived counts:** Overview 54 → 55 games; Q3 intro 14 → 23 paid games.
- **Data-covered end date:** 13 → 12 Aug 2020, now shown as a UTC date.

## 1. Q4 markers under UTC days

Before A3, markers sat on the flagged UTC `activity_date`, but their height came from a Berlin-date daily average of
the same 5-minute data. Now every marker sits on the UTC day's actual players, which is the value the detector
tested.
- All 375 flagged days were drawn before, too. None lacked a complete Berlin day.
- 14 markers moved by more than 10% in height, 50 by 2–10%, and 311 by less than 2%.
- The biggest moves are events that start in the late UTC evening:
  - Path of Exile league launches: the UTC day is 30% higher than the Berlin day.
  - No Man's Sky "NEXT": 26%.
  - Final Fantasy XIV maintenance drops.

```sql
with berlin as (
    select steam_app_id, cast(recorded_at as date) as day, avg(player_count) as players_berlin, count(*) as readings
    from marts.fact_player_activity
    where data_resolution = '5min'
    group by 1, 2
),
flags as (
    select a.steam_app_id, g.name, a.activity_date, a.direction, a.is_market_wide, a.z_score, a.avg_players as players_utc,
           b.players_berlin, b.readings
    from reporting.rpt_market_anomalies a
    join marts.dim_game g using (steam_app_id)
    left join berlin b on b.steam_app_id = a.steam_app_id and b.day = a.activity_date
    where a.is_anomaly
)
select
    count(*)                                                                         as flagged_days,
    count(*) filter (where players_berlin is null or readings < 230)                 as not_drawn_before,
    count(*) filter (where readings >= 230
                       and abs(players_berlin / players_utc - 1) > 0.10)              as moved_over_10pct,
    count(*) filter (where readings >= 230
                       and abs(players_berlin / players_utc - 1) between 0.02 and 0.10) as moved_2_to_10pct,
    count(*) filter (where readings >= 230
                       and abs(players_berlin / players_utc - 1) < 0.02)              as moved_under_2pct
from flags
```

Result:

| flagged_days | not_drawn_before | moved_over_10pct | moved_2_to_10pct | moved_under_2pct |
|---|---|---|---|---|
| 375 | 0 | 14 | 50 | 311 |

Markers that moved by more than 10% (top 12):

```sql
with berlin as (
    select steam_app_id, cast(recorded_at as date) as day, avg(player_count) as players_berlin, count(*) as readings
    from marts.fact_player_activity
    where data_resolution = '5min'
    group by 1, 2
),
flags as (
    select a.steam_app_id, g.name, a.activity_date, a.direction, a.is_market_wide, a.z_score, a.avg_players as players_utc,
           b.players_berlin, b.readings
    from reporting.rpt_market_anomalies a
    join marts.dim_game g using (steam_app_id)
    left join berlin b on b.steam_app_id = a.steam_app_id and b.day = a.activity_date
    where a.is_anomaly
)
select name, activity_date, direction, round(z_score, 2) as z_score,
       round(players_utc, 0) as players_utc_day, round(players_berlin, 0) as players_berlin_day,
       readings as berlin_readings, round(players_berlin / players_utc - 1, 4) as berlin_vs_utc
from flags
where players_berlin is null or readings < 230 or abs(players_berlin / players_utc - 1) > 0.10
order by abs(coalesce(players_berlin / players_utc - 1, 9)) desc
limit 12
```

Result:

| name | activity_date | direction | z_score | players_utc_day | players_berlin_day | berlin_readings | berlin_vs_utc |
|---|---|---|---|---|---|---|---|
| Path of Exile | 2020-06-19 00:00:00 | spike | 4.65 | 29057.0 | 20254.0 | 288 | -0.3029 |
| No Man's Sky | 2018-07-24 00:00:00 | spike | 6.0 | 11421.0 | 8505.0 | 284 | -0.2553 |
| FINAL FANTASY XIV Online | 2018-05-21 00:00:00 | drop | -9.6 | 2779.0 | 3484.0 | 288 | 0.2536 |
| FINAL FANTASY XIV Online | 2018-09-17 00:00:00 | drop | -7.15 | 2313.0 | 2873.0 | 287 | 0.2424 |
| FINAL FANTASY XIV Online | 2020-08-10 00:00:00 | drop | -9.25 | 8127.0 | 9979.0 | 287 | 0.2279 |
| FINAL FANTASY XIV Online | 2019-06-27 00:00:00 | drop | -7.21 | 6081.0 | 7224.0 | 287 | 0.188 |
| Terraria | 2020-05-16 00:00:00 | spike | 12.76 | 156607.0 | 128281.0 | 288 | -0.1809 |
| Path of Exile | 2019-12-13 00:00:00 | spike | 3.42 | 24898.0 | 20864.0 | 288 | -0.162 |
| Path of Exile | 2019-03-08 00:00:00 | spike | 3.23 | 24911.0 | 21070.0 | 288 | -0.1542 |
| Path of Exile | 2020-03-13 00:00:00 | spike | 3.79 | 29457.0 | 25240.0 | 288 | -0.1431 |
| Path of Exile | 2018-12-07 00:00:00 | spike | 4.13 | 30817.0 | 26669.0 | 288 | -0.1346 |
| Stardew Valley | 2018-04-30 00:00:00 | spike | 3.29 | 11404.0 | 9951.0 | 288 | -0.1274 |

The new band reproduces the flags exactly:

```sql
select count(*) as scored_days,
       count(*) filter (where is_anomaly) as flagged,
       count(*) filter (where (avg_players > band_upper_players or avg_players < band_lower_players)) as outside_band,
       count(*) filter (where is_anomaly <> (avg_players > band_upper_players or avg_players < band_lower_players))
           as disagreements
from reporting.rpt_market_anomalies
where anomaly_status = 'scored' and baseline_log_stddev > 0
```

Result:

| scored_days | flagged | outside_band | disagreements |
|---|---|---|---|
| 27383 | 375 | 375 | 0 |

## 4. One baseline per screen — Terraria Dec 2018

Terraria, discount 2018-12-20 to 2019-01-06 (50% off):
- The Q3 detail line averages **+56.1029%** over the 18 discount days, the same as that discount's `lift_during`,
  which feeds the side metric "Typical bump during a discount".
- Before A3, the line showed 108.6% on 28 Dec (106.5% after 7-day smoothing), against the centred ±30-day median.
  Now it shows 158.5%, against the 14 days before the discount.

SQL and result: `index_definitions_2026_09_29.md`, section S3.

## 6. Pooled metrics (kept pooled; report only)

Discounts per game behind the Q3 outcome bars and typical discount (clean discounts):

```sql
with per_game as (
    select g.name, count(*) as discounts
    from reporting.rpt_discount_effect e join marts.dim_game g using (steam_app_id)
    where e.episode_status = 'valid' and not e.post_window_confounded
    group by g.name
)
select count(*) as games, sum(discounts) as discounts, min(discounts) as min, arg_min(name, discounts) as min_game,
       median(discounts) as median, max(discounts) as max, arg_max(name, discounts) as max_game
from per_game
```

Result:

| games | discounts | min | min_game | median | max | max_game |
|---|---|---|---|---|---|---|
| 23 | 174.0 | 1 | RimWorld | 8.0 | 12 | Hearts of Iron IV |

```sql
select g.name, count(*) as discounts
from reporting.rpt_discount_effect e join marts.dim_game g using (steam_app_id)
where e.episode_status = 'valid' and not e.post_window_confounded
group by g.name order by discounts desc, g.name
```

Result:

| name | discounts |
|---|---|
| Hearts of Iron IV | 12 |
| DayZ | 11 |
| Cities: Skylines | 10 |
| PAYDAY 2 | 10 |
| Dead Cells | 9 |
| Divinity: Original Sin 2 - Definitive Edition | 9 |
| Terraria | 9 |
| The Witcher 3: Wild Hunt - Complete Edition | 9 |
| 7 Days to Die | 8 |
| Euro Truck Simulator 2 | 8 |
| Fallout 4 | 8 |
| No Man's Sky | 8 |
| Stellaris | 8 |
| The Elder Scrolls V: Skyrim Special Edition | 8 |
| DARK SOULS™ III | 7 |
| Rust | 7 |
| Stardew Valley | 7 |
| Subnautica | 7 |
| Tom Clancy's Rainbow Six Siege | 6 |
| PUBG: BATTLEGROUNDS | 5 |
| Slay the Spire | 5 |
| Counter-Strike 2 | 2 |
| RimWorld | 1 |

Q4 surge ratio with and without No Man's Sky. No Man's Sky has 21 of the 106 surges on deep-discount days:

```sql
select * from (
with paid as (
    select *,
           case when coalesce(sale_discount_pct, -1) <= 0 then 'No discount'
                when sale_discount_pct <= 49 then 'Discount, under 50% off'
                else 'Discount, 50% off or more' end as bucket,
           is_anomaly and direction = 'spike' and not is_market_wide as surge
    from reporting.rpt_market_anomalies
    where anomaly_status = 'scored'
      and steam_app_id in (select steam_app_id from reporting.rpt_market_anomalies where during_sale)
      
),
rates as (
    select bucket, count(*) as days, count(*) filter (where surge) as surges, count(*) filter (where surge) / count(*) as rate
    from paid group by bucket
)
select 'all paid games' as scope, (select count(distinct steam_app_id) from paid) as games,
       max(days)   filter (where bucket = 'No discount')               as no_discount_days,
       max(surges) filter (where bucket = 'No discount')               as no_discount_surges,
       max(days)   filter (where bucket = 'Discount, 50% off or more') as deep_days,
       max(surges) filter (where bucket = 'Discount, 50% off or more') as deep_surges,
       round(max(rate) filter (where bucket = 'Discount, 50% off or more')
             / max(rate) filter (where bucket = 'No discount'), 2)    as ratio
from rates
)
union all
select * from (
with paid as (
    select *,
           case when coalesce(sale_discount_pct, -1) <= 0 then 'No discount'
                when sale_discount_pct <= 49 then 'Discount, under 50% off'
                else 'Discount, 50% off or more' end as bucket,
           is_anomaly and direction = 'spike' and not is_market_wide as surge
    from reporting.rpt_market_anomalies
    where anomaly_status = 'scored'
      and steam_app_id in (select steam_app_id from reporting.rpt_market_anomalies where during_sale)
      and steam_app_id <> 275850   -- No Man's Sky
),
rates as (
    select bucket, count(*) as days, count(*) filter (where surge) as surges, count(*) filter (where surge) / count(*) as rate
    from paid group by bucket
)
select 'without No Man''s Sky' as scope, (select count(distinct steam_app_id) from paid) as games,
       max(days)   filter (where bucket = 'No discount')               as no_discount_days,
       max(surges) filter (where bucket = 'No discount')               as no_discount_surges,
       max(days)   filter (where bucket = 'Discount, 50% off or more') as deep_days,
       max(surges) filter (where bucket = 'Discount, 50% off or more') as deep_surges,
       round(max(rate) filter (where bucket = 'Discount, 50% off or more')
             / max(rate) filter (where bucket = 'No discount'), 2)    as ratio
from rates
)
```

Result:

| scope | games | no_discount_days | no_discount_surges | deep_days | deep_surges | ratio |
|---|---|---|---|---|---|---|
| all paid games | 23 | 18527 | 64 | 2294 | 106 | 13.38 |
| without No Man's Sky | 22 | 17788 | 61 | 2099 | 85 | 11.81 |

```sql
select count(*) filter (where steam_app_id = 275850) as nms_deep_surges, count(*) as all_deep_surges
from reporting.rpt_market_anomalies
where anomaly_status = 'scored' and is_anomaly and direction = 'spike' and not is_market_wide and sale_discount_pct >= 50
```

Result:

| nms_deep_surges | all_deep_surges |
|---|---|
| 21 | 106 |

Without No Man's Sky the ratio is **11.8×** instead of 13.4×. The headline "about 13×" depends partly on one game.

## Layer checks

- Reporting reads only marts, **plus 4 references between reporting models**:
  - `rpt_lifecycle_curve → rpt_game_lifecycle`
  - `rpt_lifecycle_typical_curve → rpt_lifecycle_curve`
  - `rpt_discount_typical → rpt_discount_effect`
  - `rpt_discount_effect_daily → rpt_discount_effect`

  These rollups reuse the question model's launch peak or baseline instead of copying its logic.
  `DATA_MODEL.md` now allows reporting to read other `rpt_*` models of the same question.
- Nothing outside reporting and observability reads reporting. Nothing reads observability.
- Facts → `dim_game` joins are unchanged (the approved exception).

## Not changed

- Hourly timestamps (Game explorer live chart, "latest reading", Overview) are still displayed in Berlin time,
  labelled "Berlin time". They are clock times, not day definitions.
- The O1 and H3 ratios stay in dashboard SQL: one stored column divided by another; their captions state 100%.
- The Q3 side metric "Typical bump" is a median of one game's discounts, computed in pandas; it uses the same
  baseline as the line.
