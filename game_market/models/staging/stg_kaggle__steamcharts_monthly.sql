with source as (

    select
        month,
        avg_players,
        gain,
        gain_percent,
        peak_players,
        name,
        steam_appid
    from {{ source('kaggle_raw', 'steamcharts_monthly') }}

),

parsed as (

    select
        steam_appid::bigint as steam_app_id,
        name as steamcharts_name,
        strptime(month, '%b-%y')::date as activity_month,
        try_cast(nullif(avg_players, '-') as double) as avg_players,
        try_cast(nullif(peak_players, '-') as double) as peak_players,
        try_cast(nullif(gain, '-') as double) as gain,
        try_cast(nullif(gain_percent, '-') as double) as gain_percent,
        gain = '-' as is_first_tracked_month
    from source
    where steam_appid is not null

)

select *
from parsed