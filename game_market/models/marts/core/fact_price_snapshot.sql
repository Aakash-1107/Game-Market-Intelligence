WITH staging AS (
    SELECT * FROM {{ ref('stg_itad__price_history') }}
),

deduplicated AS (
    SELECT *
    FROM staging
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY itad_game_id, shop_id, observed_at
        ORDER BY observed_at
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
    INNER JOIN {{ ref('dim_game') }} g
        ON d.steam_app_id = g.steam_app_id
)

SELECT * FROM final