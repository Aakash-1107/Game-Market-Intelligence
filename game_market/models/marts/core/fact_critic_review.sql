with reviews as (
    select
        review_id,
        steam_app_id,
        opencritic_id,
        oc_game_id,
        outlet_id,
        outlet_name,
        platform_name,
        np_score,
        raw_score,
        score_base,
        median_at_review,
        published_at,
        fetched_at_utc
    from {{ ref('stg_opencritic__reviews') }}
),

games as (
    select game_key, steam_app_id
    from {{ ref('dim_game') }}
)

select
    md5(r.review_id || '|' || r.steam_app_id::varchar) as critic_review_key,
    g.game_key,
    r.steam_app_id,
    r.opencritic_id,
    r.oc_game_id,
    r.review_id,
    r.outlet_id,
    r.outlet_name,
    r.platform_name,
    r.np_score,
    r.raw_score,
    r.score_base,
    r.median_at_review,
    r.published_at,
    r.fetched_at_utc
from reviews r
inner join games g on r.steam_app_id = g.steam_app_id