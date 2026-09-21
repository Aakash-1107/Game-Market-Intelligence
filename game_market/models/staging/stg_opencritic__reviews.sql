with raw as (
    select
        steam_app_id,
        opencritic_id,
        fetched_at_utc::timestamptz                         as fetched_at_utc,
        unnest(reviews)                                     as review
    from read_json(
        's3://game-market-raw/raw/opencritic/reviews/*/*/*/*.json',
        format        = 'auto',
        union_by_name = true
    )
),

extracted as (
    select
        steam_app_id::integer                               as steam_app_id,
        opencritic_id::varchar                              as opencritic_id,
        fetched_at_utc,

        -- review identity
        review->>'_id'                                      as review_id,
        (review->'game'->>'id')::integer                    as oc_game_id,

        -- publication
        (review->>'publishedDate')::timestamptz             as published_at,
        review->>'language'                                 as language,

        -- scores
        (review->>'npScore')::numeric                       as np_score,
        (review->>'score')::numeric                         as raw_score,
        (review->'ScoreFormat'->>'base')::numeric           as score_base,
        (review->>'medianAtTimeOfReview')::numeric          as median_at_review,

        -- outlet
        (review->'Outlet'->>'id')::integer                  as outlet_id,
        review->'Outlet'->>'name'                           as outlet_name,

        -- platform (first platform only — most reviews cover one)
        review->'Platforms'->0->>'name'                     as platform_name

    from raw
)

select *
from extracted
where language = 'en-us'   -- English reviews only
  and np_score is not null  -- drop reviews with no usable score