-- Q3 header: the typical discount by depth. Grain: one row per depth bucket (max_discount_pct):
-- under_50 (< 50% off), 50_to_74 (50-74% off), 75_or_more (>= 75% off).
-- Same clean discounts as rpt_discount_typical (episode_status = 'valid' and no other discount within 28 days
-- after it ends); lift = during the discount vs the 14 days before it (baseline_avg).
-- few_cases: fewer than 10 discounts in the bucket, too few to read the median as typical.

with clean as (
    select
        steam_app_id,
        max_discount_pct,
        lift_during
    from {{ ref('rpt_discount_effect') }}
    where episode_status = 'valid'
      and not post_window_confounded
),

bucketed as (
    select
        case
            when max_discount_pct < 50 then 'under_50'
            when max_discount_pct < 75 then '50_to_74'
            else '75_or_more'
        end                             as depth_bucket,
        steam_app_id,
        lift_during
    from clean
),

buckets as (
    select * from (values
        (1, 'under_50',   '< 50% off'),
        (2, '50_to_74',   '50–74% off'),
        (3, '75_or_more', '≥ 75% off')
    ) as t(bucket_order, depth_bucket, depth_label)
)

select
    b.depth_bucket,
    b.bucket_order,
    b.depth_label,
    count(k.lift_during)                        as n_discounts,
    count(distinct k.steam_app_id)              as n_games,
    median(k.lift_during)                       as median_lift_during,
    avg(k.lift_during)                          as mean_lift_during,
    count(k.lift_during) < 10                   as few_cases
from buckets b
left join bucketed k on k.depth_bucket = b.depth_bucket
group by b.depth_bucket, b.bucket_order, b.depth_label
