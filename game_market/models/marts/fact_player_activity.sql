with player_counts as (

    select
        steam_app_id,
        game_name,
        player_count,
        recorded_at

    from {{ ref('stg_steam__player_counts') }}

),

games as (

    select
        game_key,
        steam_app_id

    from {{ ref('dim_game') }}

),

final as (

    select
        md5(
            p.steam_app_id::varchar || '|' || p.recorded_at::varchar
        )                           as activity_key,
        g.game_key,
        p.steam_app_id,
        p.game_name,
        p.player_count,
        p.recorded_at,
        'hourly'::varchar           as data_resolution

    from player_counts p
    inner join games g
        on p.steam_app_id = g.steam_app_id

)

select * from final