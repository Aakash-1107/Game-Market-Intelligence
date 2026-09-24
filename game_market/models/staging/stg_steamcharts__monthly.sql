-- Grain: one row per game per calendar month (latest fetch wins).
-- 'Last 30 Days' is a rolling window, not a calendar month, and is excluded.
-- Any other unparseable month label surfaces as a NULL activity_month (tested).

with source as (
    select
        steam_app_id,
        month_label,
        avg_players,
        gain,
        gain_pct,
        peak_players,
        fetched_at_utc
    from {{ source('steamcharts_raw', 'monthly') }}
),

parsed as (
    select
        cast(steam_app_id as integer)                                      as steam_app_id,
        month_label,
        cast(try_strptime(month_label, '%B %Y') as date)                   as activity_month,
        try_cast(nullif(avg_players, '-') as double)                       as avg_players,
        try_cast(nullif(gain, '-') as double)                              as gain,
        try_cast(nullif(replace(gain_pct, '%', ''), '-') as double)        as gain_percent,
        try_cast(nullif(peak_players, '-') as double)                      as peak_players,
        cast(fetched_at_utc as timestamptz)                                as fetched_at_utc
    from source
    where month_label <> 'Last 30 Days'
)

select
    steam_app_id,
    month_label,
    activity_month,
    avg_players,
    gain,
    gain_percent,
    peak_players,
    fetched_at_utc
from parsed
qualify row_number() over (
    partition by steam_app_id, activity_month
    order by fetched_at_utc desc
) = 1