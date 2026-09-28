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
    a.last_hourly_at
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
