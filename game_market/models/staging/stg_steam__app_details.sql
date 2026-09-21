with raw as (

    select *
    from read_json(
        's3://{{ env_var("AWS_BUCKET") }}/raw/steam/app_details/*/*/*/app_details_*.json',
        union_by_name = true,
        ignore_errors = true
    )

),

extracted as (

    select
        -- wrapper fields
        cast(steam_app_id as integer)               as steam_app_id,
        cast(fetched_at_utc as timestamptz)         as fetched_at_utc,

        -- core metadata
        data->>'name'                               as name,
        data->>'type'                               as app_type,
        cast(data->>'is_free' as boolean)           as is_free,
        data->>'short_description'                  as short_description,
        data->>'header_image'                       as header_image_url,

        -- release date as raw string — parsed in mart
        data->'release_date'->>'date'               as release_date_raw,
        cast(
            data->'release_date'->>'coming_soon'
            as boolean
        )                                           as coming_soon,

        -- metacritic — nullable
        try_cast(
            data->'metacritic'->>'score'
            as integer
        )                                           as metacritic_score,

        -- platforms
        cast(data->'platforms'->>'windows' as boolean) as platform_windows,
        cast(data->'platforms'->>'mac'     as boolean) as platform_mac,
        cast(data->'platforms'->>'linux'   as boolean) as platform_linux,

        -- recommendations — nullable
        try_cast(
            data->'recommendations'->>'total'
            as integer
        )                                           as total_recommendations,

        -- developers array → comma-separated string
        (
            select string_agg(val, ', ')
            from unnest(
                json_extract_string(data, '$.developers[*]')
            ) t(val)
        )                                           as developers,

        -- publishers array → comma-separated string
        (
            select string_agg(val, ', ')
            from unnest(
                json_extract_string(data, '$.publishers[*]')
            ) t(val)
        )                                           as publishers,

        -- genres array → comma-separated descriptions
        (
            select string_agg(
                json_extract_string(g, '$.description'), ', '
            )
            from unnest(
                json_extract(data, '$.genres[*]')
            ) t(g)
        )                                           as steam_genres

    from raw
    where data is not null

),

deduplicated as (

    select *
    from (
        select
            *,
            row_number() over (
                partition by steam_app_id
                order by fetched_at_utc desc
            ) as rn
        from extracted
    ) ranked
    where rn = 1

)

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
from deduplicated