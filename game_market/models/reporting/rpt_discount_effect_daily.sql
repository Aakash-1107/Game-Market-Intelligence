-- Q3 game detail. Grain: one row per valid discount episode per UTC day in its window
-- (14 days before the discount to 28 days after it ends), complete 5-minute days only.
-- 100% = that episode's baseline_avg (average daily players in the 14 days before the discount), the same
-- baseline as lift_during / lift_post_* in rpt_discount_effect, so the line and the metrics agree.
-- A day can belong to two episodes when their windows overlap; each episode is its own series.

with episodes as (
    select
        sale_episode_key,
        steam_app_id,
        sale_start,
        sale_end,
        max_discount_pct,
        baseline_avg,
        lift_during
    from {{ ref('rpt_discount_effect') }}
    where episode_status = 'valid'
),

daily as (
    select
        steam_app_id,
        activity_date,
        avg_players
    from {{ ref('fact_player_activity_daily') }}
    where data_resolution = '5min'
      and is_complete_day
)

select
    md5(e.sale_episode_key || '|' || cast(d.activity_date as varchar)) as episode_day_key,
    e.sale_episode_key,
    e.steam_app_id,
    d.activity_date,
    case
        when d.activity_date < e.sale_start then 'before'
        when d.activity_date <= e.sale_end then 'during'
        when d.activity_date <= e.sale_end + 7 then 'first_week_after'
        else 'weeks_2_4_after'
    end                                         as phase,
    e.sale_start,
    e.sale_end,
    e.max_discount_pct,
    d.avg_players,
    e.baseline_avg,
    d.avg_players / e.baseline_avg              as vs_baseline,
    e.lift_during
from episodes e
inner join daily d
    on d.steam_app_id = e.steam_app_id
   and d.activity_date between e.sale_start - 14 and e.sale_end + 28
