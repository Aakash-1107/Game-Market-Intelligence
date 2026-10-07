-- Grain: one row per game per UTC day (5-minute backfill days and hourly collection days).
-- Thin gold copy of int_player_activity_daily: aggregation and completeness logic stay in intermediate.

with daily as (

    select
        steam_app_id,
        activity_date,
        data_resolution,
        avg_players,
        peak_players,
        min_players,
        observation_count,
        expected_observations,
        completeness_ratio,
        is_complete_day
    from {{ ref('int_player_activity_daily') }}

)

select
    md5(cast(d.steam_app_id as varchar) || '|' || cast(d.activity_date as varchar)) as activity_day_key,
    g.game_key,
    d.steam_app_id,
    d.activity_date,
    d.data_resolution,
    d.avg_players,
    d.peak_players,
    d.min_players,
    d.observation_count,
    d.expected_observations,
    d.completeness_ratio,
    d.is_complete_day
from daily d
inner join {{ ref('dim_game') }} g
    on d.steam_app_id = g.steam_app_id
