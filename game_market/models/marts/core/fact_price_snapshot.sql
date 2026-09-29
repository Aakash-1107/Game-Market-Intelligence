WITH staging AS (
    SELECT * FROM {{ ref('stg_itad__price_history') }}
),

-- Since 2026-09-28 stg_itad__price_history already guarantees this grain (same rule, plus latest fetch wins);
-- this step is kept as a no-op safeguard.
-- ITAD sometimes records two different prices for the same game, shop and second (30 cases, 23 on Steam),
-- typically a real deal row plus a 0.00 / 0% row. Keep exactly one, deterministically:
--   1. prefer any row that is not "price 0 and discount 0" (the 0.00 / 0% rows are artefacts),
--   2. then the deepest discount,
--   3. then the lowest price.
-- (The previous ORDER BY observed_at sorted by a partition column, so the kept row was arbitrary.)
deduplicated AS (
    SELECT *
    FROM staging
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY itad_game_id, shop_id, observed_at
        ORDER BY (price_amount = 0 AND discount_pct = 0), discount_pct DESC, price_amount
    ) = 1
),

final AS (
    SELECT
        md5(itad_game_id || '|' || shop_id::TEXT || '|' || observed_at::TEXT) AS snapshot_id,
        g.game_key,
        d.steam_app_id,
        d.itad_game_id,
        d.shop_id,
        d.shop_name,
        d.observed_at,
        d.price_amount,
        d.price_amount_int,
        d.regular_amount,
        d.regular_amount_int,
        d.discount_pct,
        d.currency,
        CASE WHEN d.discount_pct > 0 THEN TRUE ELSE FALSE END AS is_on_sale
    FROM deduplicated d
    -- INNER JOIN defines the scope: only games in dim_game (= tracked_games seed with Steam appdetails).
    -- ITAD history for untracked games (e.g. Dying Light, 239140) stays in raw but is excluded here.
    INNER JOIN {{ ref('dim_game') }} g
        ON d.steam_app_id = g.steam_app_id
)

SELECT * FROM final