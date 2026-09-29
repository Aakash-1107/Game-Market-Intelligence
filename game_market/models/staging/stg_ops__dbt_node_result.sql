{{ config(tags=['observability']) }}  -- reads the Neon logs (source ops): excluded in analytics-only builds

-- Grain: one dbt node x dbt invocation (daily-flow builds), read live from Neon.

select
    run_id,
    invocation_id,
    unique_id,
    resource_type,
    status,
    status in ('error', 'fail')                             as is_error,   -- a failed model/seed or a failing test
    execution_time_s,
    rows_affected,
    failures,
    message,
    generated_at
from {{ source('ops', 'dbt_node_result') }}
