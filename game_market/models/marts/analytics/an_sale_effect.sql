{{ config(materialized='table') }}

-- Q3 Sale effect. Grain: one row per sale episode (from int_sale_episodes).
-- Activity: complete days of the 5-minute backfill only (Dec 2017 - Aug 2020).
-- Observational: lifts are associations, not causal effects.

with episodes as (
    select
        sale_episode_key,
        steam_app_id,
        sale_start,
        sale_end,
        sale_days,
        max_discount_pct,
        avg_discount_pct,
        prev_sale_end,
        next_sale_start
    from {{ ref('int_sale_episodes') }}
),

daily as (
    select
        steam_app_id,
        activity_date,
        avg_players
    from {{ ref('int_player_activity_daily') }}
    where data_resolution = '5min'
      and is_complete_day
),

phased as (
    select
        e.sale_episode_key,
        d.avg_players,
        case
            when d.activity_date between e.sale_start - 14 and e.sale_start - 1 then 'baseline'
            when d.activity_date between e.sale_start and e.sale_end then 'during'
            when d.activity_date between e.sale_end + 1 and e.sale_end + 7 then 'post_early'
            when d.activity_date between e.sale_end + 8 and e.sale_end + 28 then 'post_late'
        end as phase
    from episodes e
    inner join daily d
        on d.steam_app_id = e.steam_app_id
       and d.activity_date between e.sale_start - 14 and e.sale_end + 28
),

agg as (
    select
        sale_episode_key,
        avg(case when phase = 'baseline'   then avg_players end) as baseline_avg,
        avg(case when phase = 'during'     then avg_players end) as during_avg,
        avg(case when phase = 'post_early' then avg_players end) as post_early_avg,
        avg(case when phase = 'post_late'  then avg_players end) as post_late_avg,
        count(case when phase = 'baseline'   then 1 end) as baseline_days,
        count(case when phase = 'during'     then 1 end) as during_days,
        count(case when phase = 'post_early' then 1 end) as post_early_days,
        count(case when phase = 'post_late'  then 1 end) as post_late_days
    from phased
    group by sale_episode_key
),

scored as (
    select
        e.sale_episode_key,
        e.steam_app_id,
        e.sale_start,
        e.sale_end,
        e.sale_days,
        e.max_discount_pct,
        e.avg_discount_pct,
        a.baseline_avg,
        a.during_avg,
        a.post_early_avg,
        a.post_late_avg,
        coalesce(a.baseline_days, 0)   as baseline_days,
        coalesce(a.during_days, 0)     as during_days,
        coalesce(a.post_early_days, 0) as post_early_days,
        coalesce(a.post_late_days, 0)  as post_late_days,
        a.during_avg     / nullif(a.baseline_avg, 0) - 1 as lift_during,
        a.post_early_avg / nullif(a.baseline_avg, 0) - 1 as lift_post_early,
        a.post_late_avg  / nullif(a.baseline_avg, 0) - 1 as lift_post_late,
        coalesce(e.next_sale_start <= e.sale_end + 28, false) as post_window_confounded,
        case
            when a.sale_episode_key is null then 'no_activity_data'
            when e.prev_sale_end is not null and e.prev_sale_end >= e.sale_start - 14 then 'baseline_contaminated'
            when coalesce(a.baseline_days, 0) < 12 then 'insufficient_baseline'
            when coalesce(a.during_days, 0) < 0.8 * e.sale_days then 'insufficient_during'
            when coalesce(a.post_late_days, 0) < 15 then 'insufficient_post'
            else 'valid'
        end as episode_status
    from episodes e
    left join agg a on e.sale_episode_key = a.sale_episode_key
)

select
    s.sale_episode_key,
    g.game_key,
    s.steam_app_id,
    g.name,
    s.sale_start,
    s.sale_end,
    s.sale_days,
    s.max_discount_pct,
    s.avg_discount_pct,
    s.baseline_avg,
    s.during_avg,
    s.post_early_avg,
    s.post_late_avg,
    s.baseline_days,
    s.during_days,
    s.post_early_days,
    s.post_late_days,
    s.lift_during,
    s.lift_post_early,
    s.lift_post_late,
    s.post_window_confounded,
    s.episode_status,
    case
        when s.episode_status <> 'valid' then null
        when s.lift_during < 0.05 then 'no_lift'
        when abs(s.lift_post_late) <= 0.10 then 'returned_to_baseline'
        when s.lift_post_late > 0.10 then 'elevated_after'
        else 'below_baseline_after'
    end as sale_outcome
from scored s
inner join {{ ref('dim_game') }} g on s.steam_app_id = g.steam_app_id
