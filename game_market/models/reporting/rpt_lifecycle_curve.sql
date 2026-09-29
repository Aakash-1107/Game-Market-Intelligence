-- Q1 curves. Grain: one row per game per month since its Steam release (months 0-24),
-- for games whose launch is observed (rpt_game_lifecycle.lifecycle_status = 'launch_observed').
-- 100% = the game's launch peak: busiest month from the release month to 3 months later.

with games as (
    select
        game_key,
        steam_app_id,
        name,
        release_month,
        lifecycle_pattern,
        launch_peak_avg
    from {{ ref('rpt_game_lifecycle') }}
    where lifecycle_status = 'launch_observed'
),

monthly as (
    select
        steam_app_id,
        activity_month,
        avg_players
    from {{ ref('fact_player_activity_monthly') }}
)

select
    g.game_key,
    g.steam_app_id,
    g.name,
    g.lifecycle_pattern,
    g.lifecycle_pattern <> 'insufficient_history'                  as is_settled,  -- >= 1 year since launch
    date_diff('month', g.release_month, m.activity_month)          as month_index,
    m.activity_month,
    m.avg_players,
    g.launch_peak_avg,
    m.avg_players / g.launch_peak_avg                              as vs_launch_peak
from games g
inner join monthly m
    on m.steam_app_id = g.steam_app_id
where date_diff('month', g.release_month, m.activity_month) between 0 and 24
