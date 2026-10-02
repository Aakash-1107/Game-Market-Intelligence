{{ config(tags=['observability']) }}

-- Returns the components whose health_status breaks the rules in mart_pipeline_health (expected: no rows).
--   fail: never succeeded, latest attempt failed / partial / skipped, or dbt_build's latest invocation failed;
--   warn: last success older than ok_hours (hourly 2 h, daily sources and dbt_build 26 h);
--   ok:   otherwise.
-- Reads the view's own last_status and hours, so it checks the CASE and the thresholds, not the log parsing.
-- dbt_build's invocation flag is not exposed by the view, so a dbt_build `fail` is accepted when nothing else
-- explains it.

with h as (
    select * from {{ ref('mart_pipeline_health') }}
),

expected as (
    select
        *,
        case
            when last_success_at is null                            then 'fail'
            when last_status in ('failed', 'partial', 'skipped')    then 'fail'
            when hours_since_last_success > ok_hours                then 'warn'
            else 'ok'
        end as expected_status
    from h
)

select component, health_status, expected_status, last_status, hours_since_last_success, ok_hours
from expected
where (health_status <> expected_status and not (component = 'dbt_build' and health_status = 'fail'))
   -- the thresholds the rules promise
   or (component = 'hourly_player_counts' and ok_hours <> 2)
   or (component <> 'hourly_player_counts' and ok_hours <> 26)
