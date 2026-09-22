{{ config(materialized='table') }}

with daily as (

    select
        steam_app_id,
        activity_date as period_start,
        activity_date as period_end,
        'day' as period_grain,
        data_resolution,
        avg_players,
        peak_players,
        is_complete_day
    from {{ ref('int_player_activity_daily') }}

),

monthly as (

    select
        steam_app_id,
        activity_month as period_start,
        (activity_month + interval '1 month' - interval '1 day')::date as period_end,
        'month' as period_grain,
        data_resolution,
        avg_players,
        peak_players,
        null as is_complete_day
    from {{ ref('fact_player_activity_monthly') }}

),

unioned as (

    select * from daily
    union all
    select * from monthly

),

with_lifecycle_position as (

    select
        u.steam_app_id,
        g.game_key,
        u.period_start,
        u.period_end,
        u.period_grain,
        u.data_resolution,
        u.avg_players,
        u.peak_players,
        u.is_complete_day,
        g.first_observed_date,
        g.had_pre_release_tracking,
        date_diff('day', g.first_observed_date, u.period_start) as days_since_first_observed
    from unioned u
    inner join {{ ref('int_game_first_observed') }} g
        on u.steam_app_id = g.steam_app_id

)

select
    md5(steam_app_id || '|' || period_grain || '|' || period_start::text || '|' || data_resolution) as lifecycle_key,
    *
from with_lifecycle_position
order by steam_app_id, period_start