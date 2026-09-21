with app_details as (

    select
        steam_app_id,
        name,
        app_type,
        is_free,
        short_description,
        header_image_url,
        release_date_raw,
        coming_soon,
        metacritic_score,
        platform_windows,
        platform_mac,
        platform_linux,
        total_recommendations,
        developers,
        publishers,
        steam_genres,
        fetched_at_utc
    from {{ ref('stg_steam__app_details') }}

),

app_list as (

    select
        steam_app_id,
        app_name
    from {{ ref('stg_steam__app_list') }}

),

final as (

    select
        md5(cast(d.steam_app_id as varchar))        as game_key,
        d.steam_app_id,

        -- name: prefer appdetails, fall back to app_list
        coalesce(d.name, a.app_name)                as name,

        d.app_type,
        d.is_free,
        d.short_description,
        d.header_image_url,

        coalesce(
            try_strptime(d.release_date_raw, '%d %b, %Y'),
            try_strptime(d.release_date_raw, '%-d %b, %Y')
        )                                           as release_date,
        d.release_date_raw,
        d.coming_soon,

        d.metacritic_score,
        d.platform_windows,
        d.platform_mac,
        d.platform_linux,
        d.total_recommendations,
        d.developers,
        d.publishers,
        d.steam_genres,
        d.fetched_at_utc                            as details_fetched_at

    from app_details d
    left join app_list a
        on d.steam_app_id = a.steam_app_id

)

select * from final