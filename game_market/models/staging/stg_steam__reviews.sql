with source as (

    select *
    from {{ source('steam_raw', 'reviews') }}

),

flattened as (

    select
        steam_app_id::integer                                       as steam_app_id,
        fetched_at::timestamptz                                     as fetched_at,
        unnest(reviews)                                             as review

    from source

),

final as (

    select
        steam_app_id,
        fetched_at,
        review.recommendationid::varchar                            as recommendation_id,
        to_timestamp(review.timestamp_created::bigint)::timestamptz as review_created_at,
        to_timestamp(review.timestamp_updated::bigint)::timestamptz as review_updated_at,
        review.voted_up::boolean                                    as voted_up,
        review.votes_up::integer                                    as votes_up,
        review.weighted_vote_score::float                           as weighted_vote_score,
        review.steam_purchase::boolean                              as steam_purchase,
        review.received_for_free::boolean                           as received_for_free,
        review.written_during_early_access::boolean                 as written_during_early_access,
        review.playtime_at_review::integer                          as playtime_at_review_minutes,
        review.playtime_forever::integer                            as playtime_forever_minutes

    from flattened

    where review.recommendationid is not null

)

-- Grain: one row per (steam_app_id, recommendation_id). Raw is append-only, and Steam's cursor
-- pagination also repeats reviews across pages within one fetch (~13% of rows on 2026-09-28),
-- with author playtime/votes updated between pages. Latest fetch wins; within a fetch, the most
-- recent snapshot of the review wins.
select * from final
qualify row_number() over (
    partition by steam_app_id, recommendation_id
    order by
        fetched_at desc,
        review_updated_at desc,
        playtime_forever_minutes desc nulls last,
        votes_up desc nulls last,
        weighted_vote_score desc nulls last
) = 1