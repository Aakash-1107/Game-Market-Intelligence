-- Grain: one row per game per day of Steam price (shop 61), forward-filled between ITAD price events.
-- Thin gold copy of int_price_daily: spine, forward-fill and freshness logic stay in intermediate.

with daily as (

    select
        steam_app_id,
        price_date,
        price_amount,
        regular_amount,
        discount_pct,
        is_on_sale,
        last_price_event_date,
        days_since_price_event,
        price_freshness,
        currency
    from {{ ref('int_price_daily') }}

)

select
    md5(cast(d.steam_app_id as varchar) || '|' || cast(d.price_date as varchar)) as price_day_key,
    g.game_key,
    d.steam_app_id,
    d.price_date,
    d.price_amount,
    d.regular_amount,
    d.discount_pct,
    d.is_on_sale,
    d.last_price_event_date,
    d.days_since_price_event,
    d.price_freshness,
    d.currency
from daily d
inner join {{ ref('dim_game') }} g
    on d.steam_app_id = g.steam_app_id
