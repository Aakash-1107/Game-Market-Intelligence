-- Grain: one row per Steam discount period per game (maximal run of consecutive discounted days).
-- Thin gold copy of int_sale_episodes: the gaps-and-islands logic stays in intermediate.
-- Column names still say "sale" (= Steam discount period, not units sold); renames are deferred.

with episodes as (

    select
        steam_app_id,
        sale_start,
        sale_end,
        sale_days,
        max_discount_pct,
        avg_discount_pct,
        prev_sale_end,
        next_sale_start
    from {{ ref('int_sale_episodes') }}

)

select
    md5(cast(e.steam_app_id as varchar) || '|' || cast(e.sale_start as varchar)) as sale_episode_key,
    g.game_key,
    e.steam_app_id,
    e.sale_start,
    e.sale_end,
    e.sale_days,
    e.max_discount_pct,
    e.avg_discount_pct,
    e.prev_sale_end,
    e.next_sale_start
from episodes e
inner join {{ ref('dim_game') }} g
    on e.steam_app_id = g.steam_app_id
