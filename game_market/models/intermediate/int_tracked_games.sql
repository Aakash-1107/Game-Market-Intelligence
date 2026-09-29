-- Grain: one row per game in scope. The single place the tracked-games restriction is defined.
-- Scope = tracked_games seed (all rows; is_active only steers ingestion) that also has Steam appdetails.
-- A seed game without appdetails (e.g. Dying Light, 239140: appdetails returns success=false) is out of scope.
-- dim_game and every intermediate model inner-join this, so one rule decides which games reach the marts.

with tracked as (

    select
        cast(steam_app_id as integer)   as steam_app_id
    from {{ ref('tracked_games') }}

),

details as (

    select
        steam_app_id
    from {{ ref('stg_steam__app_details') }}

)

select distinct
    t.steam_app_id
from tracked t
inner join details d
    on t.steam_app_id = d.steam_app_id
