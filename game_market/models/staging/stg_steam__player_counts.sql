-- depends_on: {{ source('steam_raw', 'player_counts') }}

with source as (

    select *
    from read_parquet('s3://game-market-raw/raw/steam/player_counts/**/*.parquet')

),

renamed as (

    select
        appid::integer          as steam_app_id,
        game_name::varchar      as game_name,
        player_count::integer   as player_count,
        recorded_at::timestamp  as recorded_at

    from source

    where player_count is not null

)

select * from renamed