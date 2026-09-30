-- Grain: one row per monitored source per UTC day, from the source's first logged day to today (days without any
-- attempt are kept with zeros, e.g. the hourly collector outage on 2026-09-18).
-- expected = active games x slots per day (hourly: 24, daily sources: 1). Active games = the tracked_games seed
-- today (is_active), so days before a game was added read slightly below 100%.
-- completeness_pct = succeeded slots / expected: hourly = distinct (game, clock hour) with a success;
-- daily sources = distinct games with a success that day. games_attempted = distinct games with any log row that day.

with log as (
    select
        component,
        logged_at,
        logged_date_utc,
        steam_app_id,
        is_success,
        is_failure,
        rows_affected
    from {{ ref('stg_ops__ingestion_log') }}
    where component is not null
),

components as (
    select * from (values
        ('hourly_player_counts', 24),
        ('prices', 1),
        ('app_details', 1),
        ('reviews', 1),
        ('steamcharts_monthly', 1)
    ) as t(component, slots_per_day)
),

active as (
    select count(*) as active_games
    from {{ ref('tracked_games') }}
    where is_active
),

spine as (
    select
        l.component,
        cast(d.day as date) as activity_date
    from (select component, min(logged_date_utc) as first_day from log group by component) l,
         range(l.first_day, cast(now() at time zone 'UTC' as date) + 1, interval 1 day) as d(day)
),

per_day as (
    select
        component,
        logged_date_utc                                                         as activity_date,
        count(*)                                                                as attempts,
        count(*) filter (where is_success)                                      as successes,
        count(*) filter (where is_failure)                                      as failures,
        sum(rows_affected)                                                      as rows_affected,
        count(distinct steam_app_id) filter (where is_success)                  as games_succeeded,
        count(distinct steam_app_id)                                            as games_attempted,
        count(distinct (steam_app_id, date_trunc('hour', logged_at))) filter (where is_success) as game_hours_succeeded
    from log
    group by component, logged_date_utc
)

select
    s.component,
    s.activity_date,
    coalesce(p.attempts, 0)                                                     as attempts,
    coalesce(p.successes, 0)                                                    as successes,
    coalesce(p.failures, 0)                                                     as failures,
    coalesce(p.rows_affected, 0)                                                as rows_affected,
    coalesce(p.games_succeeded, 0)                                              as games_succeeded,
    coalesce(p.games_attempted, 0)                                              as games_attempted,
    a.active_games * c.slots_per_day                                            as expected,
    case when c.slots_per_day = 24 then coalesce(p.game_hours_succeeded, 0)
         else coalesce(p.games_succeeded, 0) end                                as succeeded_slots,
    round(100.0 * case when c.slots_per_day = 24 then coalesce(p.game_hours_succeeded, 0)
                       else coalesce(p.games_succeeded, 0) end
          / (a.active_games * c.slots_per_day), 1)                              as completeness_pct
from spine s
inner join components c on c.component = s.component
cross join active a
left join per_day p on p.component = s.component and p.activity_date = s.activity_date
