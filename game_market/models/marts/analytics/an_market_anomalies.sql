{{ config(materialized='table') }}

-- Q4 anomalies. Grain: one row per game per day, scope = 5-minute backfill only (21 games, Dec 2017-Aug 2020).
-- z-score vs trailing 28-day baseline (excluding the day itself). Observational: flags days, does not claim cause.

with daily as (
    select
        steam_app_id,
        activity_date,
        avg_players,
        ln(avg_players) as log_players
    from {{ ref('int_player_activity_daily') }}
    where data_resolution = '5min'
      and is_complete_day
      and avg_players > 0
),

baseline as (
    select
        d.steam_app_id,
        d.activity_date,
        d.log_players,
        avg(b.log_players)    as baseline_mean,
        stddev_samp(b.log_players) as baseline_stddev,
        count(b.log_players)  as baseline_days
    from daily d
    left join daily b
        on b.steam_app_id = d.steam_app_id
       and b.activity_date between d.activity_date - 28 and d.activity_date - 1
    group by d.steam_app_id, d.activity_date, d.log_players
),

scored as (
    select
        steam_app_id,
        activity_date,
        log_players,
        baseline_mean,
        baseline_stddev,
        baseline_days,
        case when baseline_days >= 21 and baseline_stddev > 0
             then (log_players - baseline_mean) / baseline_stddev
             end as z_score,
        case when baseline_days < 21 then 'insufficient_baseline' else 'scored' end as anomaly_status
    from baseline
),

sale_flag as (
    -- episodes are contiguous islands per game, so at most one per game-day
    select
        steam_app_id,
        sale_start + cast(i as integer) as flagged_date,
        sale_start,
        max_discount_pct
    from {{ ref('int_sale_episodes') }}, range(0, sale_days) as t(i)
),

flagged as (
    select
        s.*,
        coalesce(s.anomaly_status = 'scored' and abs(s.z_score) >= 3, false) as is_anomaly,
        case when s.anomaly_status = 'scored' and s.z_score > 0 then 'spike'
             when s.anomaly_status = 'scored' and s.z_score < 0 then 'drop' end as direction
    from scored s
),

-- Same-day, same-direction anomalies across games point to a platform-wide cause
-- (e.g. the 2019-08-14 Steam outage: 7 games dropped together), not a game-specific event.
same_day as (
    select activity_date, direction, count(*) as games_flagged_same_day
    from flagged
    where is_anomaly
    group by activity_date, direction
)

select
    md5(cast(f.steam_app_id as varchar) || '|' || cast(f.activity_date as varchar)) as anomaly_key,
    g.game_key,
    f.steam_app_id,
    f.activity_date,
    f.z_score,
    f.anomaly_status,
    f.is_anomaly,
    f.direction,
    case when f.is_anomaly then sd.games_flagged_same_day end as games_flagged_same_day,
    coalesce(f.is_anomaly and sd.games_flagged_same_day >= 3, false) as is_market_wide,
    sf.flagged_date is not null as during_sale,
    sf.max_discount_pct as sale_discount_pct,
    sf.sale_start,
    coalesce(abs(date_diff('day', cast(g.release_date as date), f.activity_date)) <= 7, false) as near_release
from flagged f
inner join {{ ref('dim_game') }} g on f.steam_app_id = g.steam_app_id
left join sale_flag sf on sf.steam_app_id = f.steam_app_id and sf.flagged_date = f.activity_date
left join same_day sd on sd.activity_date = f.activity_date and sd.direction = f.direction
