{{ config(materialized='table') }}

with source as (

    select
        steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent
    from {{ ref('stg_kaggle__steamcharts_monthly') }}

),

joined as (

    select
        md5(source.steam_app_id || '|' || source.activity_month::text) as activity_monthly_key,
        dim_game.game_key,
        source.steam_app_id,
        source.activity_month,
        source.avg_players,
        source.peak_players,
        source.gain,
        source.gain_percent,
        'monthly' as data_resolution
    from source
    inner join {{ ref('dim_game') }} as dim_game
        on source.steam_app_id = dim_game.steam_app_id

)

select * from joined