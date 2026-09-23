{{ config(materialized='table') }}

/*
Core 3 — Current trajectory: where is a game's player activity heading?

Grain: one row per tracked game per calendar month, post-1.0 months only
       (months before dim_game.release_date are excluded, per the launch-anchor decision).
Source: fact_player_activity_monthly (Kaggle SteamCharts, Jul 2012 – Sep 2025).

Metrics (trailing 12 calendar months, ending at activity_month):
  monthly_trend        exp(regr_slope(ln(avg_players), month_index)) - 1
  volatility           stddev of month-over-month ln changes (consecutive months only)
  pct_of_peak_to_date  avg_players / max(avg_players) over all months up to this one
  months_present       months with a usable (> 0) avg_players value in the window

Status rules (first match wins):
  launch_phase       months_since_release < 6
  insufficient_data  months_present < 10
  growing            monthly_trend >  +2%
  stable             -2% <= monthly_trend <= +2%
  slow_decline       -5% <= monthly_trend <  -2%
  steep_decline      monthly_trend < -5%
is_high_volatility is a separate flag (threshold provisional, to be calibrated).

Edge cases:
  avg_players NULL or 0 -> excluded from the regression (ln undefined), lowers months_present
  missing calendar months -> window is calendar-based (RANGE on month_index), not row-based
  release_date NULL -> no launch_phase check, all months kept
*/

with params as (
    select
        10   as min_months_present,
        6    as launch_phase_months,
        0.02 as stable_band,
        0.05 as steep_decline,
        0.25 as high_volatility_sd   -- provisional
),

monthly as (
    select
        f.steam_app_id,
        f.activity_month,
        f.avg_players,
        cast(date_trunc('month', g.release_date) as date) as release_month,
        year(f.activity_month) * 12 + month(f.activity_month) as month_index,
        case when f.avg_players > 0 then ln(f.avg_players) end as ln_avg_players
    from {{ ref('fact_player_activity_monthly') }} as f
    inner join {{ ref('dim_game') }} as g
        on g.steam_app_id = f.steam_app_id
    where g.release_date is null
       or f.activity_month >= date_trunc('month', g.release_date)
),

with_changes as (
    select
        steam_app_id,
        activity_month,
        avg_players,
        release_month,
        month_index,
        ln_avg_players,
        case
            when month_index - lag(month_index) over w_prev = 1
            then ln_avg_players - lag(ln_avg_players) over w_prev
        end as ln_change
    from monthly
    window w_prev as (partition by steam_app_id order by month_index)
),

windowed as (
    select
        steam_app_id,
        activity_month,
        avg_players,
        datediff('month', release_month, activity_month) as months_since_release,
        count(ln_avg_players)                     over w_12m as months_present,
        regr_slope(ln_avg_players, month_index)   over w_12m as ln_slope,
        stddev_samp(ln_change)                    over w_12m as volatility,
        avg_players / nullif(
            max(avg_players) over (
                partition by steam_app_id
                order by month_index
                rows between unbounded preceding and current row
            ), 0
        ) as pct_of_peak_to_date
    from with_changes
    window w_12m as (
        partition by steam_app_id
        order by month_index
        range between 11 preceding and current row
    )
)

select
    md5(cast(w.steam_app_id as varchar) || '|' || cast(w.activity_month as varchar)) as trajectory_key,
    w.steam_app_id,
    w.activity_month,
    w.avg_players,
    w.months_since_release,
    w.months_present,
    exp(w.ln_slope) - 1 as monthly_trend,
    w.volatility,
    w.pct_of_peak_to_date,
    case
        when w.months_since_release < p.launch_phase_months then 'launch_phase'
        when w.months_present < p.min_months_present         then 'insufficient_data'
        when exp(w.ln_slope) - 1 >  p.stable_band            then 'growing'
        when exp(w.ln_slope) - 1 >= -p.stable_band           then 'stable'
        when exp(w.ln_slope) - 1 >= -p.steep_decline         then 'slow_decline'
        else 'steep_decline'
    end as trajectory_status,
    coalesce(w.volatility > p.high_volatility_sd, false) as is_high_volatility
from windowed as w
cross join params as p