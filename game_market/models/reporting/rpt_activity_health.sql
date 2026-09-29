{{ config(materialized='table') }}

-- Q2 Activity health. Grain: one row per game in dim_game.
-- Window: 12 months ending at the latest month in fact_player_activity_monthly.
-- Thresholds (3%/month, r2 0.5, 9 months) are documented assumptions.

with monthly as (
    select
        steam_app_id,
        activity_month,
        avg_players
    from {{ ref('fact_player_activity_monthly') }}
    where avg_players is not null
),

bounds as (
    select
        max(activity_month)                                   as window_end,
        cast(max(activity_month) - interval 11 month as date) as window_start
    from monthly
),

first_seen as (
    select
        steam_app_id,
        min(activity_month) as first_month
    from monthly
    group by steam_app_id
),

windowed as (
    select
        m.steam_app_id,
        m.activity_month,
        m.avg_players,
        date_diff('month', b.window_start, m.activity_month) as month_num
    from monthly m
    cross join bounds b
    where m.activity_month between b.window_start and b.window_end
      and m.avg_players > 0
),

with_changes as (
    select
        steam_app_id,
        activity_month,
        avg_players,
        month_num,
        ln(avg_players / lag(avg_players) over (
            partition by steam_app_id order by activity_month
        )) as log_change
    from windowed
),

stats as (
    select
        steam_app_id,
        count(*)                                               as months_in_window,
        avg(case when month_num <= 2 then avg_players end)     as start_level_3m,
        avg(case when month_num >= 9 then avg_players end)     as current_level_3m,
        case when count(*) >= 2
            then regr_slope(ln(avg_players), month_num)
        end                                                as log_slope,
        regr_r2(ln(avg_players), month_num)                    as trend_r2,
        stddev_samp(log_change)                                as volatility
    from with_changes
    group by steam_app_id
),

classified as (
    select
        g.game_key,
        g.steam_app_id,
        g.name,
        b.window_start,
        b.window_end,
        f.first_month,
        coalesce(s.months_in_window, 0)                         as months_in_window,
        s.start_level_3m,
        s.current_level_3m,
        s.current_level_3m / nullif(s.start_level_3m, 0) - 1    as change_12m_pct,
        exp(s.log_slope) - 1                                    as trend_monthly_pct,
        s.trend_r2,
        s.volatility,
        case
            when s.current_level_3m is null then null
            when s.current_level_3m < 1000 then 'small'
            when s.current_level_3m < 10000 then 'medium'
            when s.current_level_3m < 100000 then 'large'
            else 'very_large'
        end as size_tier,
        case
            when f.steam_app_id is null then 'no_monthly_data'
            when f.first_month > b.window_start then 'too_recent'
            when coalesce(s.months_in_window, 0) < 9 then 'insufficient_history'
            when exp(s.log_slope) - 1 <= -0.03 and s.trend_r2 >= 0.5 then 'declining'
            when exp(s.log_slope) - 1 >= 0.03 and s.trend_r2 >= 0.5 then 'growing'
            when abs(exp(s.log_slope) - 1) < 0.03 then 'stable'
            else 'volatile'
        end as health_class
    from {{ ref('dim_game') }} g
    cross join bounds b
    left join first_seen f on g.steam_app_id = f.steam_app_id
    left join stats s on g.steam_app_id = s.steam_app_id
)

select
    game_key,
    steam_app_id,
    name,
    window_start,
    window_end,
    first_month,
    months_in_window,
    start_level_3m,
    current_level_3m,
    change_12m_pct,
    trend_monthly_pct,
    trend_r2,
    volatility,
    size_tier,
    health_class,
    case
        when health_class in ('declining', 'growing', 'stable', 'volatile')
        then rank() over (
            partition by size_tier, health_class in ('declining', 'growing', 'stable', 'volatile')
            order by trend_monthly_pct desc
        )
    end as trend_rank_in_tier
from classified
