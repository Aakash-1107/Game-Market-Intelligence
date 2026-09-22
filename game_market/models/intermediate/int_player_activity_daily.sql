{{ config(materialized='table') }}

with observations as (

    select
        steam_app_id,
        recorded_at,
        player_count,
        data_resolution,
        cast(recorded_at at time zone 'UTC' as date) as activity_date
    from {{ ref('fact_player_activity') }}
    where player_count is not null

),

daily as (

    select
        steam_app_id,
        activity_date,
        data_resolution,
        avg(player_count)                as avg_players,
        max(player_count)                as peak_players,
        min(player_count)                as min_players,
        count(*)                         as observation_count,
        case data_resolution
            when '5min'   then 288
            when 'hourly' then 24
            else null
        end                              as expected_observations
    from observations
    group by steam_app_id, activity_date, data_resolution

)

select
    md5(steam_app_id || '|' || activity_date || '|' || data_resolution) as activity_day_key,
    steam_app_id,
    activity_date,
    data_resolution,
    avg_players,
    peak_players,
    min_players,
    observation_count,
    expected_observations,
    round(observation_count::double / expected_observations, 4) as completeness_ratio,
    observation_count::double / expected_observations >= 0.8    as is_complete_day
from daily