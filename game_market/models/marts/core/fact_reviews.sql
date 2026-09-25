with reviews as (

    select
        steam_app_id,
        recommendation_id,
        review_created_at,
        review_updated_at,
        voted_up,
        votes_up,
        weighted_vote_score,
        steam_purchase,
        received_for_free,
        written_during_early_access,
        playtime_at_review_minutes,
        playtime_forever_minutes

    from {{ ref('stg_steam__reviews') }}

),

games as (

    select
        game_key,
        steam_app_id

    from {{ ref('dim_game') }}

),

final as (

    select
        md5(
            r.steam_app_id::varchar || '|' || r.recommendation_id
        )                                               as review_key,
        g.game_key,
        r.steam_app_id,
        r.recommendation_id,
        r.review_created_at,
        r.review_updated_at,
        r.voted_up,
        r.votes_up,
        r.weighted_vote_score,
        r.steam_purchase,
        r.received_for_free,
        r.written_during_early_access,
        r.playtime_at_review_minutes,
        r.playtime_forever_minutes

    from reviews r
    inner join games g
        on r.steam_app_id = g.steam_app_id

)

select * from final