{{ config(materialized='table') }}

-- Grain: one row per game per calendar month.
-- Source priority: SteamCharts scrape (re-fetchable, current to last complete month)
-- over Kaggle (static CC0 snapshot of SteamCharts, ends 2025-09).
-- Kaggle rows are used only for game-months SteamCharts does not provide.
-- Known limitation: gain/gain_percent come from the source row; at a
-- Kaggle-filled month the gain may refer to a neighbour from the other source.

with steamcharts as (

    select
        cast(steam_app_id as integer) as steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        'steamcharts' as source,
        1             as source_priority
    from {{ ref('stg_steamcharts__monthly') }}

),

kaggle as (

    select
        cast(steam_app_id as integer) as steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        'kaggle' as source,
        2        as source_priority
    from {{ ref('stg_kaggle__steamcharts_monthly') }}

),

combined as (

    select steam_app_id, activity_month, avg_players, peak_players, gain, gain_percent, source, source_priority
    from steamcharts
    union all
    select steam_app_id, activity_month, avg_players, peak_players, gain, gain_percent, source, source_priority
    from kaggle

),

ranked as (

    select
        steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        source,
        row_number() over (
            partition by steam_app_id, activity_month
            order by source_priority
        ) as rn
    from combined

),

joined as (

    select
        md5(ranked.steam_app_id || '|' || ranked.activity_month::text) as activity_monthly_key,
        dim_game.game_key,
        ranked.steam_app_id,
        ranked.activity_month,
        ranked.avg_players,
        ranked.peak_players,
        ranked.gain,
        ranked.gain_percent,
        'monthly' as data_resolution,
        ranked.source
    from ranked
    inner join {{ ref('dim_game') }} as dim_game
        on ranked.steam_app_id = dim_game.steam_app_id
    where ranked.rn = 1

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
