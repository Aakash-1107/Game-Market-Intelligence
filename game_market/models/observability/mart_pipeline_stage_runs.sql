{{ config(materialized='view') }}

-- Grain: one row per daily-flow run x stage (pipeline_run_log), newest first when read by the dashboard.
-- A VIEW for the same reason as mart_pipeline_health: it must show runs that happened after the last dbt build.
-- A thin pass-through of the staging view, so the dashboard reads the observability layer only.

select
    run_id,
    flow_name,
    stage,
    component,
    status,
    started_at,
    finished_at,
    duration_s,
    records_in,
    records_out,
    error_message
from {{ ref('stg_ops__pipeline_run_log') }}
