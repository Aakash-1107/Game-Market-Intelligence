-- Grain: one row per game in the tracked_games seed (active and inactive).
-- What each tracked game actually received, read from staging so games that dim_game drops (no appdetails) still show.
-- Check this after adding a game to tracked_games.csv.

with tracked as (

    select
        cast(steam_app_id as integer)               as steam_app_id,
        game_name,
        is_active
    from {{ ref('tracked_games') }}

),

details as (
    select distinct steam_app_id from {{ ref('stg_steam__app_details') }}
),

in_dim as (
    select steam_app_id from {{ ref('dim_game') }}
),

itad as (
    select steam_app_id, source_game_id, status
    from {{ ref('stg_source_id_mapping') }}
    where source = 'itad'
),

opencritic as (
    select steam_app_id, status
    from {{ ref('stg_source_id_mapping') }}
    where source = 'opencritic'
),

prices as (
    select steam_app_id, count(*) as price_rows, max(observed_at) as last_price_event_at
    from {{ ref('stg_itad__price_history') }}
    group by steam_app_id
),

activity as (
    select
        steam_app_id,
        count(*) filter (where data_resolution = 'hourly')      as hourly_rows,
        max(recorded_at) filter (where data_resolution = 'hourly') as last_hourly_at,
        count(*) filter (where data_resolution = '5min')        as backfill_5min_rows
    from {{ ref('stg_steam__player_counts') }}
    group by steam_app_id
),

monthly as (
    select steam_app_id, count(*) as monthly_rows
    from (
        select steam_app_id, activity_month from {{ ref('stg_steamcharts__monthly') }}
        union
        select cast(steam_app_id as integer), activity_month from {{ ref('stg_kaggle__steamcharts_monthly') }}
    )
    group by steam_app_id
),

reviews as (
    select steam_app_id, count(*) as review_rows
    from {{ ref('stg_steam__reviews') }}
    group by steam_app_id
),

critic as (
    select steam_app_id, count(*) as critic_review_rows
    from {{ ref('stg_opencritic__reviews') }}
    group by steam_app_id
),

-- Q1-Q4 membership, using the same rule each dashboard page applies
q1 as (
    select steam_app_id, lifecycle_status
    from {{ ref('rpt_game_lifecycle') }}
),

q2 as (
    select steam_app_id, health_class
    from {{ ref('rpt_activity_health') }}
),

steam_prices as (
    select distinct steam_app_id
    from {{ ref('int_price_daily') }}   -- Steam shop only
),

q3 as (
    select
        steam_app_id,
        count(*)                                                      as sale_episodes,
        count(*) filter (where episode_status = 'valid')              as valid_episodes,
        count(*) filter (where episode_status <> 'no_activity_data')  as episodes_with_activity,
        mode(episode_status) filter (where episode_status not in ('valid', 'no_activity_data')) as top_invalid_status
    from {{ ref('rpt_discount_effect') }}
    group by steam_app_id
),

q4 as (
    select
        steam_app_id,
        count(*)                                                      as complete_days,
        count(*) filter (where anomaly_status = 'scored')             as scored_days
    from {{ ref('rpt_market_anomalies') }}
    group by steam_app_id
)

select
    t.steam_app_id,
    t.game_name,
    t.is_active,
    i.steam_app_id is not null                      as in_dim_game,
    d.steam_app_id is not null                      as has_details,
    coalesce(it.status in ('matched_auto', 'matched_manual', 'matched_imported'), false) as has_itad_id,
    it.status                                       as itad_status,
    it.source_game_id                               as itad_game_id,
    coalesce(p.price_rows, 0) > 0                   as has_prices,
    coalesce(a.hourly_rows, 0) > 0                  as has_hourly_activity,
    coalesce(a.backfill_5min_rows, 0) > 0           as has_5min_backfill,
    coalesce(m.monthly_rows, 0) > 0                 as has_monthly_activity,
    coalesce(r.review_rows, 0) > 0                  as has_reviews,
    coalesce(c.critic_review_rows, 0) > 0           as has_critic_reviews,
    oc.status                                       as opencritic_status,
    coalesce(p.price_rows, 0)                       as price_rows,
    coalesce(a.hourly_rows, 0)                      as hourly_rows,
    coalesce(a.backfill_5min_rows, 0)               as backfill_5min_rows,
    coalesce(m.monthly_rows, 0)                     as monthly_rows,
    coalesce(r.review_rows, 0)                      as review_rows,
    coalesce(c.critic_review_rows, 0)               as critic_review_rows,
    p.last_price_event_at,
    a.last_hourly_at,

    -- Q1 Life after launch (1_Lifecycle): lifecycle_status = 'launch_observed'
    coalesce(q1.lifecycle_status = 'launch_observed', false) as in_q1_lifecycle,
    case
        when i.steam_app_id is null                          then 'not in dim_game (no Steam app details)'
        when q1.lifecycle_status = 'launch_observed'         then null
        when q1.lifecycle_status = 'no_monthly_data'         then 'no monthly activity'
        when q1.lifecycle_status = 'no_release_date'         then 'no parseable release date'
        when q1.lifecycle_status = 'released_after_coverage' then 'released after the last month of monthly data'
        when q1.lifecycle_status = 'launch_not_observed'     then 'monthly data starts more than a month after release'
        else q1.lifecycle_status
    end                                                      as q1_reason,

    -- Q2 Activity health (2_Activity_Health): a health class was assigned
    coalesce(q2.health_class in ('declining', 'growing', 'stable', 'volatile'), false) as in_q2_activity_health,
    case
        when i.steam_app_id is null                          then 'not in dim_game (no Steam app details)'
        when q2.health_class in ('declining', 'growing', 'stable', 'volatile') then null
        when q2.health_class = 'no_monthly_data'             then 'no monthly activity'
        when q2.health_class = 'too_recent'                  then 'monthly data starts inside the 12-month window'
        when q2.health_class = 'insufficient_history'        then 'fewer than 9 months in the 12-month window'
        else q2.health_class
    end                                                      as q2_reason,

    -- Q3 Do sales bring players (3_Sale_Effect): at least one valid sale episode.
    -- Activity is 5-minute backfill only (2017-12 to 2020-08); hourly data never enters.
    coalesce(q3.valid_episodes > 0, false)                   as in_q3_sale_effect,
    case
        when i.steam_app_id is null                          then 'not in dim_game (no Steam app details)'
        when q3.valid_episodes > 0                           then null
        when sp.steam_app_id is null                         then 'no Steam price history'
        when coalesce(q3.sale_episodes, 0) = 0               then 'never on sale on Steam'
        when coalesce(a.backfill_5min_rows, 0) = 0           then 'no 5-minute activity (Q3 uses only the 2017-2020 backfill)'
        when q3.episodes_with_activity = 0                   then 'no sale overlaps the 5-minute activity'
        else 'no valid sale episode (most often ' || q3.top_invalid_status || ')'
    end                                                      as q3_reason,

    -- Q4 Unusual days (4_Market_Events): at least one scored day.
    -- Activity is 5-minute backfill only (2017-12 to 2020-08); hourly data never enters.
    coalesce(q4.scored_days > 0, false)                      as in_q4_market_events,
    case
        when i.steam_app_id is null                          then 'not in dim_game (no Steam app details)'
        when q4.scored_days > 0                              then null
        when coalesce(a.backfill_5min_rows, 0) = 0           then 'no 5-minute activity (Q4 uses only the 2017-2020 backfill)'
        when coalesce(q4.complete_days, 0) = 0               then 'no complete 5-minute days'
        else 'fewer than 21 days of history'
    end                                                      as q4_reason
from tracked t
left join in_dim i      on t.steam_app_id = i.steam_app_id
left join details d     on t.steam_app_id = d.steam_app_id
left join itad it       on t.steam_app_id = it.steam_app_id
left join opencritic oc on t.steam_app_id = oc.steam_app_id
left join prices p      on t.steam_app_id = p.steam_app_id
left join activity a    on t.steam_app_id = a.steam_app_id
left join monthly m     on t.steam_app_id = m.steam_app_id
left join reviews r     on t.steam_app_id = r.steam_app_id
left join critic c      on t.steam_app_id = c.steam_app_id
left join q1            on t.steam_app_id = q1.steam_app_id
left join q2            on t.steam_app_id = q2.steam_app_id
left join steam_prices sp on t.steam_app_id = sp.steam_app_id
left join q3            on t.steam_app_id = q3.steam_app_id
left join q4            on t.steam_app_id = q4.steam_app_id
