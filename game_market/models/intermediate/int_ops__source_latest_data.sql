{{ config(tags=['observability']) }}  -- reads the Neon logs (source ops): excluded in analytics-only builds

-- Grain: one row per monitored data source: the newest data timestamp in the warehouse, as of this dbt build.
-- Taken from each staging model's own fetch / ingest timestamp. Exception: stg_itad__price_history exposes no fetch
-- timestamp (fetched_at_utc is used inside the model but not selected; observed_at is a price-event date), so prices
-- use the last successful ITAD price fetch logged in ingestion_log instead.

select 'hourly_player_counts' as component, 'stg_steam__player_counts' as staging_model, 'recorded_at' as timestamp_column,
       max(recorded_at) as latest_data_at
from {{ ref('stg_steam__player_counts') }}
where data_resolution = 'hourly'

union all
select 'prices', 'stg_ops__ingestion_log', 'logged_at (itad / price_history, success)', max(logged_at)
from {{ ref('stg_ops__ingestion_log') }}
where component = 'prices' and is_success

union all
select 'app_details', 'stg_steam__app_details', 'fetched_at_utc', max(fetched_at_utc)
from {{ ref('stg_steam__app_details') }}

union all
select 'reviews', 'stg_steam__reviews', 'fetched_at', max(fetched_at)
from {{ ref('stg_steam__reviews') }}

union all
select 'steamcharts_monthly', 'stg_steamcharts__monthly', 'fetched_at_utc', max(fetched_at_utc)
from {{ ref('stg_steamcharts__monthly') }}
