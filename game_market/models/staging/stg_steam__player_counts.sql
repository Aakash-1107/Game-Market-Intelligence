-- depends_on: {{ source('steam_raw', 'player_counts') }}

with live as (

    select
        appid::integer              as steam_app_id,
        player_count::integer       as player_count,
        recorded_at::timestamptz    as recorded_at,
        'hourly'::varchar           as data_resolution

    from read_parquet('s3://game-market-raw/raw/steam/player_counts/[0-9][0-9][0-9][0-9]/**/*.parquet')

    where player_count is not null

),

backfill as (

    select
        steam_app_id::integer       as steam_app_id,
        player_count::integer       as player_count,
        recorded_at::timestamptz    as recorded_at,
        data_resolution::varchar    as data_resolution

    from read_parquet('s3://game-market-raw/raw/steam/player_counts/backfill/**/*.parquet')

    where player_count is not null

),

combined as (

    select * from live
    union all
    select * from backfill

)

select * from combined