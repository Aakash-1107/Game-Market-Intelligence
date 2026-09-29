{{ config(materialized='table') }}

-- Grain: one row per game per calendar month.
-- Source merge (SteamCharts priority, Kaggle fallback) lives in int_player_activity_monthly__merged;
-- this fact adds the surrogate and dimension keys.

with merged as (

    select
        steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        source
    from {{ ref('int_player_activity_monthly__merged') }}

),

joined as (

    select
        md5(merged.steam_app_id || '|' || merged.activity_month::text) as activity_monthly_key,
        dim_game.game_key,
        merged.steam_app_id,
        merged.activity_month,
        merged.avg_players,
        merged.peak_players,
        merged.gain,
        merged.gain_percent,
        'monthly' as data_resolution,
        merged.source
    from merged
    inner join {{ ref('dim_game') }} as dim_game
        on merged.steam_app_id = dim_game.steam_app_id

)

select
    activity_monthly_key,
    game_key,
    steam_app_id,
    activity_month,
    avg_players,
    peak_players,
    gain,
    gain_percent,
    data_resolution,
    source
from joined
