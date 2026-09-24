{{ config(materialized='table') }}

-- Q1 Lifecycle. Grain: one row per game in dim_game (54).
-- Metrics populated only when lifecycle_status = 'launch_observed'.
-- month_index = 0 is the release month (dim_game.release_date, decision 2026-09-23).
-- Pre-release months (month_index < 0) are used only for launch_type.
-- All retention/recovery metrics are relative to the LAUNCH peak (months 0-3),
-- not the all-time peak, so late revivals do not distort early-lifecycle metrics.

with games as (
    select
        game_key,
        steam_app_id,
        name,
        cast(date_trunc('month', cast(release_date as date)) as date) as release_month
    from {{ ref('dim_game') }}
),

monthly as (
    select
        steam_app_id,
        activity_month,
        avg_players
    from {{ ref('fact_player_activity_monthly') }}
    where avg_players is not null
),

coverage as (
    select
        steam_app_id,
        min(activity_month) as first_month,
        max(activity_month) as last_month
    from monthly
    group by steam_app_id
),

game_status as (
    select
        g.game_key,
        g.steam_app_id,
        g.name,
        g.release_month,
        c.first_month,
        c.last_month,
        case
            when c.steam_app_id is null then 'no_monthly_data'
            when g.release_month is null then 'no_release_date'
            when g.release_month > c.last_month then 'released_after_coverage'
            when c.first_month > g.release_month + interval 1 month then 'launch_not_observed'
            else 'launch_observed'
        end as lifecycle_status
    from games g
    left join coverage c on g.steam_app_id = c.steam_app_id
),

indexed as (
    select
        m.steam_app_id,
        m.avg_players,
        date_diff('month', s.release_month, m.activity_month) as month_index
    from monthly m
    inner join game_status s on m.steam_app_id = s.steam_app_id
    where s.lifecycle_status = 'launch_observed'
),

pre_release as (
    select
        steam_app_id,
        count(*)         as pre_release_months,
        max(avg_players) as pre_release_peak_avg
    from indexed
    where month_index < 0
    group by steam_app_id
),

post_release as (
    select steam_app_id, month_index, avg_players
    from indexed
    where month_index >= 0
),

launch as (
    select
        steam_app_id,
        max(avg_players)                  as launch_peak_avg,
        arg_max(month_index, avg_players) as launch_peak_month_index
    from post_release
    where month_index <= 3
    group by steam_app_id
),

summary as (
    select
        steam_app_id,
        count(*)                          as months_observed,
        max(month_index)                  as last_month_index,
        max(avg_players)                  as alltime_peak_avg,
        arg_max(month_index, avg_players) as alltime_peak_month_index,
        max(case when month_index = 6  then avg_players end) as m6_avg,
        max(case when month_index = 12 then avg_players end) as m12_avg,
        max(case when month_index = 24 then avg_players end) as m24_avg,
        arg_max(avg_players, month_index) as latest_avg_players
    from post_release
    group by steam_app_id
),

after_launch_peak as (
    select
        r.steam_app_id,
        r.month_index,
        r.avg_players,
        l.launch_peak_avg
    from post_release r
    inner join launch l on r.steam_app_id = l.steam_app_id
    where r.month_index > l.launch_peak_month_index
),

after_launch_windows as (
    select
        steam_app_id,
        month_index,
        avg_players,
        launch_peak_avg,
        avg(avg_players) over (
            partition by steam_app_id order by month_index
            rows between 2 preceding and current row
        ) as rolling_3m_avg,
        -- lowest month strictly before the current 3-month window
        min(avg_players) over (
            partition by steam_app_id order by month_index
            rows between unbounded preceding and 3 preceding
        ) as prior_low
    from after_launch_peak
),

recovery as (
    select
        steam_app_id,
        min(avg_players) as lowest_after_launch_peak,
        max(case when prior_low <= 0.5 * launch_peak_avg
                 then rolling_3m_avg / nullif(prior_low, 0) end) as max_recovery_ratio,
        min(case when prior_low <= 0.5 * launch_peak_avg
                  and rolling_3m_avg >= 0.75 * launch_peak_avg
                 then month_index end)                          as first_recovery_month_index,
        bool_or(month_index > 12 and avg_players > launch_peak_avg) as has_new_high_after_year1
    from after_launch_windows
    group by steam_app_id
)

select
    s.game_key,
    s.steam_app_id,
    s.name,
    s.release_month,
    s.first_month,
    s.last_month,
    s.lifecycle_status,

    coalesce(pr.pre_release_months, 0) as pre_release_months,
    pr.pre_release_peak_avg,
    case
        when s.lifecycle_status <> 'launch_observed' then null
        when pr.pre_release_peak_avg is null
          or pr.pre_release_peak_avg < 0.10 * l.launch_peak_avg then 'fresh_launch'
        else 'pre_release_base'
    end as launch_type,

    su.months_observed,
    su.last_month_index,
    l.launch_peak_avg,
    l.launch_peak_month_index,
    su.alltime_peak_avg,
    su.alltime_peak_month_index,
    su.m6_avg,
    su.m12_avg,
    su.m24_avg,
    su.m6_avg  / nullif(l.launch_peak_avg, 0) as retention_m6,
    su.m12_avg / nullif(l.launch_peak_avg, 0) as retention_m12,
    su.m24_avg / nullif(l.launch_peak_avg, 0) as retention_m24,
    su.latest_avg_players,
    su.latest_avg_players / nullif(l.launch_peak_avg, 0) as latest_vs_launch_peak,

    rc.lowest_after_launch_peak / nullif(l.launch_peak_avg, 0) as lowest_vs_launch_peak,
    rc.max_recovery_ratio,
    rc.first_recovery_month_index,
    case when s.lifecycle_status = 'launch_observed'
         then rc.first_recovery_month_index is not null end as has_recovery,
    rc.has_new_high_after_year1,

    case
        when s.lifecycle_status <> 'launch_observed' then null
        when su.m12_avg is null then 'insufficient_history'
        when su.m12_avg / nullif(l.launch_peak_avg, 0) < 0.30 then 'front_loaded'
        when su.m12_avg / nullif(l.launch_peak_avg, 0) < 0.60 then 'gradual_decline'
        when su.m12_avg / nullif(l.launch_peak_avg, 0) <= 1.00 then 'sustained'
        else 'growing'
    end as lifecycle_pattern

from game_status s
left join pre_release pr on s.steam_app_id = pr.steam_app_id
left join launch      l  on s.steam_app_id = l.steam_app_id
left join summary     su on s.steam_app_id = su.steam_app_id
left join recovery    rc on s.steam_app_id = rc.steam_app_id