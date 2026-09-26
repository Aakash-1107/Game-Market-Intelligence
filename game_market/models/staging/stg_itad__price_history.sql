WITH source AS (
    SELECT unnest(records) AS r
    from {{ source('itad_raw', 'price_history') }}
),

renamed AS (
    SELECT
        r.steam_app_id::INTEGER                                              AS steam_app_id,
        r.itad_game_id::TEXT                                                 AS itad_game_id,
        r.shop.id::INTEGER                                                   AS shop_id,
        r.shop.name::TEXT                                                    AS shop_name,
        timezone('Europe/Berlin', r.timestamp::TIMESTAMP)::TIMESTAMPTZ       AS observed_at,
        r.deal.price.amount::DECIMAL(10,2)                                   AS price_amount,
        r.deal.price.amountInt::INTEGER                                      AS price_amount_int,
        r.deal.regular.amount::DECIMAL(10,2)                                 AS regular_amount,
        r.deal.regular.amountInt::INTEGER                                    AS regular_amount_int,
        r.deal.cut::INTEGER                                                  AS discount_pct,
        r.deal.price.currency::TEXT                                          AS currency
    FROM source
)

SELECT * FROM renamed