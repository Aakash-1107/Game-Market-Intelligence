-- Q1 typical game. Grain: one row per month since release (0-24).
-- median_vs_launch_peak = median across the settled games that have that month (n_games varies by month).
-- plateau_vs_launch_peak = median of the monthly medians for months 4-18 (same value on every row).

with medians as (
    select
        month_index,
        median(vs_launch_peak)          as median_vs_launch_peak,
        count(distinct steam_app_id)    as n_games
    from {{ ref('rpt_lifecycle_curve') }}
    where is_settled
    group by month_index
)

select
    month_index,
    median_vs_launch_peak,
    n_games,
    (select median(median_vs_launch_peak) from medians where month_index between 4 and 18) as plateau_vs_launch_peak,
    (select count(distinct steam_app_id) from {{ ref('rpt_lifecycle_curve') }} where is_settled) as n_games_total
from medians
