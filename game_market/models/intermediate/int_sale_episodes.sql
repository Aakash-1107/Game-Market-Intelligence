{{ config(materialized='table') }}

-- Grain: one row per sale episode (maximal run of consecutive is_on_sale days) per game.
-- Gaps-and-islands on the contiguous daily price spine of int_price_daily (Steam only).

with daily as (
    select
        steam_app_id,
        price_date,
        is_on_sale,
        discount_pct,
        price_date - cast(row_number() over (
            partition by steam_app_id, is_on_sale
            order by price_date
        ) as integer) as island_id
    from {{ ref('int_price_daily') }}
),

episodes as (
    select
        steam_app_id,
        min(price_date)     as sale_start,
        max(price_date)     as sale_end,
        count(*)            as sale_days,
        max(discount_pct)   as max_discount_pct,
        avg(discount_pct)   as avg_discount_pct
    from daily
    where is_on_sale
    group by steam_app_id, island_id
)

select
    md5(cast(steam_app_id as varchar) || '|' || cast(sale_start as varchar)) as sale_episode_key,
    steam_app_id,
    sale_start,
    sale_end,
    sale_days,
    max_discount_pct,
    avg_discount_pct,
    lag(sale_end) over (partition by steam_app_id order by sale_start)    as prev_sale_end,
    lead(sale_start) over (partition by steam_app_id order by sale_start) as next_sale_start
from episodes
