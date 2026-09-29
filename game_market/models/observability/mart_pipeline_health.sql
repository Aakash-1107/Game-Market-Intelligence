{{ config(materialized='view') }}

-- Grain: one row per pipeline component. A VIEW on purpose: status is computed when it is read (now()), over
-- staging views that read Neon live. A table built at dbt-build time would keep saying "healthy" if builds stopped,
-- which is exactly the failure this model must detect. Reading it needs the Neon attach (alias `ops`).
--
-- Sources: ingestion_log (every ingestion script, including the hourly flow), pipeline_run_log (daily-flow stages,
-- including stages that failed before logging any game, or were skipped), dbt_node_result (daily-flow dbt builds).
-- Thresholds (hours since last success):  hourly_player_counts ok <= 2, warn <= 6, fail > 6;
--                                          daily sources and dbt_build ok <= 26, warn <= 48, fail > 48.
-- A component is at least `warn` when its latest attempt failed, partly failed or was skipped; dbt_build is
-- `fail` when the latest recorded invocation had an error or a failing test, regardless of age.

with components as (
    select * from (values
        ('hourly_player_counts', 1,  2.0,  6.0),
        ('prices',               24, 26.0, 48.0),
        ('app_details',          24, 26.0, 48.0),
        ('reviews',              24, 26.0, 48.0),
        ('steamcharts_monthly',  24, 26.0, 48.0),
        ('dbt_build',            24, 26.0, 48.0)
    ) as t(component, expected_interval_hours, ok_hours, warn_hours)
),

log as (
    select component, logged_at, logged_date_utc, is_success, is_failure, error_message
    from {{ ref('stg_ops__ingestion_log') }}
    where component is not null
),

ingest as (
    select
        component,
        max(logged_at)                          as last_attempt_at,
        max(logged_at) filter (where is_success) as last_success_at
    from log
    group by component
),

-- the latest attempt: hourly = the latest clock hour with log rows; daily sources = the latest UTC day with log rows
latest_attempt as (
    select
        l.component,
        count(*) filter (where l.is_success)                                  as ok_rows,
        count(*) filter (where l.is_failure)                                  as failed_rows,
        arg_max(l.error_message, l.logged_at) filter (where l.is_failure)     as last_error
    from log l
    inner join ingest i on i.component = l.component
    where (l.component = 'hourly_player_counts' and date_trunc('hour', l.logged_at) = date_trunc('hour', i.last_attempt_at))
       or (l.component <> 'hourly_player_counts'
           and l.logged_date_utc = cast(i.last_attempt_at at time zone 'UTC' as date))
    group by l.component
),

ingest_status as (
    select
        i.component,
        i.last_attempt_at,
        i.last_success_at,
        case when a.failed_rows = 0 and a.ok_rows > 0 then 'success'
             when a.ok_rows > 0 then 'partial'
             else 'failed' end                  as last_status,
        a.last_error
    from ingest i
    inner join latest_attempt a on a.component = i.component
),

stage as (
    select
        component,
        max(started_at)                                     as last_attempt_at,
        arg_max(status, started_at)                         as last_status,
        arg_max(error_message, started_at)                  as last_error,
        max(finished_at) filter (where status = 'success')  as last_success_at
    from {{ ref('stg_ops__pipeline_run_log') }}
    where component is not null
    group by component
),

dbt_invocations as (
    select
        invocation_id,
        max(generated_at)                       as generated_at,
        count(*) filter (where is_error)        as errors
    from {{ ref('stg_ops__dbt_node_result') }}
    group by invocation_id
),

dbt_latest as (
    select
        'dbt_build'                                             as component,
        max(generated_at)                                       as last_attempt_at,
        max(generated_at) filter (where errors = 0)             as last_success_at,
        arg_max(errors, generated_at) > 0                       as last_invocation_failed
    from dbt_invocations
),

combined as (
    select
        c.component,
        c.expected_interval_hours,
        c.ok_hours,
        c.warn_hours,
        greatest(coalesce(i.last_attempt_at, s.last_attempt_at, d.last_attempt_at),
                 coalesce(s.last_attempt_at, i.last_attempt_at, d.last_attempt_at),
                 coalesce(d.last_attempt_at, i.last_attempt_at, s.last_attempt_at))           as last_attempt_at,
        greatest(coalesce(i.last_success_at, s.last_success_at, d.last_success_at),
                 coalesce(s.last_success_at, i.last_success_at, d.last_success_at),
                 coalesce(d.last_success_at, i.last_success_at, s.last_success_at))           as last_success_at,
        -- a flow stage row that started within 6 h of (or after) the newest game row describes the latest attempt:
        -- it also covers stages that failed or were skipped before logging any game
        case when s.last_attempt_at is not null
                  and (i.last_attempt_at is null or s.last_attempt_at > i.last_attempt_at - interval 6 hour)
             then s.last_status else i.last_status end                                      as last_status,
        case when s.last_attempt_at is not null
                  and (i.last_attempt_at is null or s.last_attempt_at > i.last_attempt_at - interval 6 hour)
             then s.last_error else i.last_error end                                        as last_error,
        coalesce(d.last_invocation_failed, false)                                           as last_invocation_failed
    from components c
    left join ingest_status i on i.component = c.component
    left join stage s on s.component = c.component
    left join dbt_latest d on d.component = c.component
),

aged as (
    select
        *,
        round(date_diff('second', last_success_at, now()) / 3600.0, 2) as hours_since_last_success
    from combined
)

select
    a.component,
    a.last_success_at,
    a.last_attempt_at,
    coalesce(a.last_status, 'never_run')                                as last_status,
    a.last_error,
    a.expected_interval_hours,
    a.hours_since_last_success,
    a.ok_hours,
    a.warn_hours,
    case
        when a.last_success_at is null                                  then 'fail'
        when a.component = 'dbt_build' and a.last_invocation_failed     then 'fail'
        when a.hours_since_last_success > a.warn_hours                  then 'fail'
        when a.hours_since_last_success > a.ok_hours
          or a.last_status in ('failed', 'partial', 'skipped')          then 'warn'
        else 'ok'
    end                                                                 as health_status,
    l.latest_data_at                                                    as latest_data_in_warehouse_at,  -- as of the last dbt build
    now()                                                               as checked_at
from aged a
left join {{ ref('int_ops__source_latest_data') }} l on l.component = a.component
