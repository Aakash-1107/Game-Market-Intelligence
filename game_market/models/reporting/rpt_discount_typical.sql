-- Q3 typical discount. Grain: one row per discount group per phase.
-- Pooled across discounts (not per game): median lift over clean episodes
-- (episode_status = 'valid' and no other discount within 28 days after it ends).
-- 100% = the average daily players in the 14 days before the discount (baseline_avg).
-- Groups: all clean discounts; 75% off or more; under 50% off (max_discount_pct).
-- mean_lift: the plain average of the same discounts, shown next to the median (a few extreme discounts pull it up).

with clean as (
    select
        steam_app_id,
        max_discount_pct,
        lift_during,
        lift_post_early,
        lift_post_late
    from {{ ref('rpt_discount_effect') }}
    where episode_status = 'valid'
      and not post_window_confounded
),

grouped as (
    select 'all' as discount_group, steam_app_id, lift_during, lift_post_early, lift_post_late from clean
    union all
    select '75_or_more', steam_app_id, lift_during, lift_post_early, lift_post_late from clean where max_discount_pct >= 75
    union all
    select 'under_50', steam_app_id, lift_during, lift_post_early, lift_post_late from clean where max_discount_pct < 50
),

stats as (
    select
        discount_group,
        count(*)                        as n_discounts,
        count(distinct steam_app_id)    as n_games,
        median(lift_during)             as median_lift_during,
        median(lift_post_early)         as median_lift_post_early,
        median(lift_post_late)          as median_lift_post_late,
        avg(lift_during)                as mean_lift_during,
        avg(lift_post_early)            as mean_lift_post_early,
        avg(lift_post_late)             as mean_lift_post_late
    from grouped
    group by discount_group
)

select discount_group, 1 as phase_order, 'before'           as phase, 0.0                    as median_lift, n_discounts, n_games, 0.0 as mean_lift from stats
union all
select discount_group, 2, 'during',           median_lift_during,     n_discounts, n_games, mean_lift_during from stats
union all
select discount_group, 3, 'first_week_after', median_lift_post_early, n_discounts, n_games, mean_lift_post_early from stats
union all
select discount_group, 4, 'weeks_2_4_after',  median_lift_post_late,  n_discounts, n_games, mean_lift_post_late from stats
