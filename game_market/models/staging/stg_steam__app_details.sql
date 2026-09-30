with raw as (

    select steam_app_id, fetched_at_utc, data, filename
    from {{ source('steam_raw', 'app_details') }}
    where data is not null

),

-- Grain: one row per game, latest fetch wins. Raw is one file per game per run, so the newest file per
-- game is picked here, before any field is extracted (only one JSON document per game gets parsed).
latest as (

    select *
    from raw
    qualify row_number() over (
        partition by cast(steam_app_id as integer)
        order by fetched_at_utc desc, filename desc
    ) = 1

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

    from latest

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
from extracted