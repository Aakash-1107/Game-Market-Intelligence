{{ config(materialized='table') }}

with activity_5min_hourly as (

    select
        steam_app_id,
        min(recorded_at)::date as first_observed_date
    from {{ ref('fact_player_activity') }}
    group by steam_app_id

),

activity_monthly as (

    select
        steam_app_id,
        min(activity_month) as first_observed_date
    from {{ ref('fact_player_activity_monthly') }}
    group by steam_app_id

),

all_sources as (

    select * from activity_5min_hourly
    union all
    select * from activity_monthly

),

earliest_per_game as (

    select
        steam_app_id,
        min(first_observed_date) as first_observed_date
    from all_sources
    group by steam_app_id

)

select
    d.game_key,
    d.steam_app_id,
    d.name,
    d.release_date,
    coalesce(e.first_observed_date, d.release_date::date) as first_observed_date,
    e.first_observed_date is not null
        and e.first_observed_date < d.release_date::date as had_pre_release_tracking
from {{ ref('dim_game') }} d
left join earliest_per_game e
    on d.steam_app_id = e.steam_app_id