{{ config(materialized='view') }}

-- Grain: one row per dbt invocation recorded by the daily flow (dbt_node_result). Manual `dbt build` runs outside
-- the flow are not recorded. started_at comes from the flow's dbt_build stage (same run_id).
-- A VIEW, not a table: a build's results are recorded only after it finishes, so a table built by that build could
-- never contain it and would always be one build behind.

with nodes as (
    select
        run_id,
        invocation_id,
        resource_type,
        status,
        execution_time_s,
        generated_at
    from {{ ref('stg_ops__dbt_node_result') }}
),

stage as (
    select
        run_id,
        started_at,
        finished_at
    from {{ ref('stg_ops__pipeline_run_log') }}
    where stage = 'dbt_build'
),

invocations as (
    select
        invocation_id,
        any_value(run_id)                                                                   as run_id,
        max(generated_at)                                                                   as generated_at,
        sum(execution_time_s)                                                               as node_time_s,
        count(*) filter (where resource_type in ('model', 'seed') and status = 'success')   as models_ok,
        count(*) filter (where resource_type in ('model', 'seed') and status = 'error')     as models_error,
        count(*) filter (where resource_type in ('model', 'seed') and status = 'skipped')   as models_skipped,
        count(*) filter (where resource_type = 'test' and status = 'pass')                  as tests_pass,
        count(*) filter (where resource_type = 'test' and status = 'warn')                  as tests_warn,
        count(*) filter (where resource_type = 'test' and status in ('fail', 'error'))      as tests_fail,
        count(*) filter (where resource_type = 'test' and status = 'skipped')               as tests_skipped
    from nodes
    group by invocation_id
)

select
    i.invocation_id,
    i.run_id,
    s.started_at,
    coalesce(s.finished_at, i.generated_at)                                                 as finished_at,
    i.generated_at,
    i.node_time_s,
    i.models_ok,
    i.models_error,
    i.models_skipped,
    i.tests_pass,
    i.tests_warn,
    i.tests_fail,
    i.tests_skipped,
    case
        when i.models_error > 0 or i.tests_fail > 0 then 'failed'
        when i.tests_warn > 0 or i.models_skipped > 0 or i.tests_skipped > 0 then 'warn'
        else 'success'
    end                                                                                     as overall_status
from invocations i
left join stage s on s.run_id = i.run_id
