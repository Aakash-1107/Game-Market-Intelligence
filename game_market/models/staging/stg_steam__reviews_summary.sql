with source as (

    select *
    from {{ source('steam_raw', 'reviews') }}

),

final as (

    select
        steam_app_id::integer                           as steam_app_id,
        fetched_at::timestamptz                         as fetched_at,
        query_summary.total_positive::integer           as total_positive,
        query_summary.total_negative::integer           as total_negative,
        query_summary.total_reviews::integer            as total_reviews,
        query_summary.review_score::integer             as review_score,
        query_summary.review_score_desc::varchar        as review_score_desc,
        round(
            query_summary.total_positive::float /
            nullif(query_summary.total_reviews::float, 0) * 100,
            2
        )                                               as positivity_pct

    from source

)

-- Grain: one row per game, latest fetch wins (raw is one file per game per run).
select * from final
qualify row_number() over (
    partition by steam_app_id
    order by fetched_at desc
) = 1