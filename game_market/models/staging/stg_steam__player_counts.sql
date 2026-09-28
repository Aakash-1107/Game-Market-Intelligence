-- depends_on: {{ source('steam_raw', 'player_counts') }}

with live as (

    select
        appid::integer              as steam_app_id,
        player_count::integer       as player_count,
        recorded_at::timestamptz    as recorded_at,
        'hourly'::varchar           as data_resolution,
        filename                    as source_file

    from read_parquet('s3://game-market-raw/raw/steam/player_counts/[0-9][0-9][0-9][0-9]/**/*.parquet', filename = true)

    where player_count is not null

),

backfill as (

    select
        steam_app_id::integer       as steam_app_id,
        player_count::integer       as player_count,
        recorded_at::timestamptz    as recorded_at,
        data_resolution::varchar    as data_resolution,
        filename                    as source_file

    from read_parquet('s3://game-market-raw/raw/steam/player_counts/backfill/**/*.parquet', filename = true)

    where player_count is not null

),

combined as (

    select * from live
    union all
    select * from backfill

)

-- Grain: one row per (steam_app_id, recorded_at). Raw is append-only, so a re-run export or
-- re-uploaded backfill file repeats observations. A live hourly observation wins over the
-- 5-minute backfill; otherwise the latest file wins (file names carry the run timestamp).
select
    steam_app_id,
    player_count,
    recorded_at,
    data_resolution
from combined
qualify row_number() over (
    partition by steam_app_id, recorded_at
    order by (data_resolution = 'hourly') desc, source_file desc
) = 1