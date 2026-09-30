with source as (

    select steam_app_id, fetched_at, query_summary, filename
    from {{ source('steam_raw', 'reviews_summary') }}

),

-- Grain: one row per game, latest fetch wins (raw is one file per game per run). The newest file per game
-- is picked before the summary fields are extracted.
latest as (

    select *
    from source
    qualify row_number() over (
        partition by steam_app_id::integer
        order by fetched_at desc, filename desc
    ) = 1

),

final as (

    select
        steam_app_id::integer                           as steam_app_id,
        fetched_at::timestamptz                         as fetched_at,
        (query_summary->>'total_positive')::integer     as total_positive,
        (query_summary->>'total_negative')::integer     as total_negative,
        (query_summary->>'total_reviews')::integer      as total_reviews,
        (query_summary->>'review_score')::integer       as review_score,
        (query_summary->>'review_score_desc')::varchar  as review_score_desc,
        round(
            (query_summary->>'total_positive')::float /
            nullif((query_summary->>'total_reviews')::float, 0) * 100,
            2
        )                                               as positivity_pct

    from latest

)

select * from final
