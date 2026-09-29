{{ config(tags=['observability']) }}  -- reads the Neon logs (source ops): excluded in analytics-only builds

-- Grain: one daily-flow run x stage, read live from Neon.

select
    run_id,
    flow_name,
    stage,
    case stage
        when 'ingest_prices'      then 'prices'
        when 'ingest_app_details' then 'app_details'
        when 'ingest_reviews'     then 'reviews'
        when 'ingest_steamcharts' then 'steamcharts_monthly'
        when 'dbt_build'          then 'dbt_build'
    end                                                     as component,   -- null for resolve_ids, freshness_check
    status,
    started_at,
    finished_at,
    date_diff('second', started_at, finished_at)            as duration_s,
    records_in,
    records_out,
    error_message
from {{ source('ops', 'pipeline_run_log') }}
