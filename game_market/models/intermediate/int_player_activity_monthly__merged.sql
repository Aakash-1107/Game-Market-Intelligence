-- Grain: one row per tracked game per calendar month.
-- Source priority: SteamCharts scrape (re-fetchable, current to last complete month)
-- over Kaggle (static CC0 snapshot of SteamCharts, ends 2025-09).
-- Kaggle rows are used only for game-months SteamCharts does not provide.
-- Known limitation: gain/gain_percent come from the source row; at a
-- Kaggle-filled month the gain may refer to a neighbour from the other source.

with steamcharts as (

    select
        cast(steam_app_id as integer) as steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        'steamcharts' as source,
        1             as source_priority
    from {{ ref('stg_steamcharts__monthly') }}

),

kaggle as (

    select
        cast(steam_app_id as integer) as steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        'kaggle' as source,
        2        as source_priority
    from {{ ref('stg_kaggle__steamcharts_monthly') }}

),

combined as (

    select steam_app_id, activity_month, avg_players, peak_players, gain, gain_percent, source, source_priority
    from steamcharts
    union all
    select steam_app_id, activity_month, avg_players, peak_players, gain, gain_percent, source, source_priority
    from kaggle

),

ranked as (

    select
        steam_app_id,
        activity_month,
        avg_players,
        peak_players,
        gain,
        gain_percent,
        source,
        row_number() over (
            partition by steam_app_id, activity_month
            order by source_priority
        ) as rn
    from combined

)

select
    r.steam_app_id,
    r.activity_month,
    r.avg_players,
    r.peak_players,
    r.gain,
    r.gain_percent,
    r.source
from ranked r
inner join {{ ref('int_tracked_games') }} t
    on r.steam_app_id = t.steam_app_id
where r.rn = 1
