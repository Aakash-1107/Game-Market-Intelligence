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

-- tracked_games seed is the authoritative game list
tracked as (

    select
        cast(steam_app_id as integer)           as steam_app_id
    from {{ ref('tracked_games') }}

),

app_list as (

    select
        steam_app_id,
        app_name
    from {{ ref('stg_steam__app_list') }}

),

-- lifetime Steam review totals; latest fetch per game so repeated ingestion runs can't fan out the grain
reviews_summary as (

    select
        steam_app_id,
        total_positive,
        total_negative,
        total_reviews,
        review_score,
        review_score_desc,
        positivity_pct
    from {{ ref('stg_steam__reviews_summary') }}
    qualify row_number() over (
        partition by steam_app_id
        order by fetched_at desc
    ) = 1

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
        d.fetched_at_utc                            as details_fetched_at,

        r.total_positive                            as review_total_positive,
        r.total_negative                            as review_total_negative,
        r.total_reviews                             as review_total_count,
        r.review_score,
        r.review_score_desc,
        r.positivity_pct                            as review_positivity_pct

    from app_details d
    inner join tracked t
        on d.steam_app_id = t.steam_app_id
    left join app_list a
        on d.steam_app_id = a.steam_app_id
    left join reviews_summary r
        on d.steam_app_id = r.steam_app_id

)

select * from final