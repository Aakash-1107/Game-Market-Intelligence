{{ config(tags=['observability']) }}  -- reads the Neon logs (source ops): excluded in analytics-only builds

-- Grain: one logged ingestion event (a game x stage x script run), read live from Neon.
-- ingestion_log.run_id defaults to a random uuid per row, so it identifies a row, not a run: group runs by time.
-- component maps the (source, stage) pairs the pipeline monitors; other rows (OpenCritic, backfill, histogram,
-- ID resolution) are manual or one-off and keep component = null.

with src as (
    select
        run_id,
        run_timestamp,
        source,
        stage,
        game_id,
        status,
        http_status,
        error_message,
        rows_affected
    from {{ source('ops', 'ingestion_log') }}
)

select
    cast(run_id as varchar)                                 as log_id,
    run_timestamp                                           as logged_at,
    cast(run_timestamp at time zone 'UTC' as date)          as logged_date_utc,
    source,
    stage,
    case
        when source = 'steam'            and stage = 'raw'             then 'hourly_player_counts'
        when source = 'itad'             and stage = 'price_history'   then 'prices'
        when source = 'steam_appdetails' and stage = 'ingestion'       then 'app_details'
        when source = 'steam_reviews'    and stage = 'fetch_reviews'   then 'reviews'
        when source = 'steamcharts'      and stage = 'extract_monthly' then 'steamcharts_monthly'
    end                                                     as component,
    try_cast(game_id as integer)                            as steam_app_id,
    status,
    status = 'success'                                      as is_success,
    status in ('failed', 'failure', 'error')                as is_failure,
    http_status,
    error_message,
    rows_affected
from src
