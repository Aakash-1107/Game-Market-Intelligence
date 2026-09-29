WITH source AS (
    SELECT
        (fetched_at_utc->>'$')::TIMESTAMPTZ AS fetched_at_utc,   -- file-level fetch time (raw JSON at maximum_depth = 1)
        unnest(records::JSON[]) AS r   -- r is raw JSON (sources.yml reads with maximum_depth = 1)
    from {{ source('itad_raw', 'price_history') }}
),

renamed AS (
    SELECT
        (r->>'steam_app_id')::INTEGER                                        AS steam_app_id,
        (r->>'itad_game_id')::TEXT                                           AS itad_game_id,
        (r->'shop'->>'id')::INTEGER                                          AS shop_id,
        (r->'shop'->>'name')::TEXT                                           AS shop_name,
        -- ITAD timestamps carry their UTC offset ("...T10:16:44+02:00"); casting the text keeps
        -- the offset, so the instant is exact and independent of the session TimeZone.
        (r->>'timestamp')::TIMESTAMPTZ                                       AS observed_at,
        (r->'deal'->'price'->>'amount')::DECIMAL(10,2)                       AS price_amount,
        (r->'deal'->'price'->>'amountInt')::INTEGER                          AS price_amount_int,
        (r->'deal'->'regular'->>'amount')::DECIMAL(10,2)                     AS regular_amount,
        (r->'deal'->'regular'->>'amountInt')::INTEGER                        AS regular_amount_int,
        (r->'deal'->>'cut')::INTEGER                                         AS discount_pct,
        (r->'deal'->'price'->>'currency')::TEXT                              AS currency,
        fetched_at_utc
    FROM source
)

-- Grain: one row per (itad_game_id, shop_id, observed_at).
-- Every run re-fetches the full history since 2010, so each run repeats all earlier records: latest fetch wins.
-- Within one fetch ITAD sometimes records two prices for the same game, shop and second (typically a real
-- deal row plus a 0.00 / 0% artefact row). Resolve deterministically: not "price 0 and discount 0" first,
-- then the deepest discount, then the lowest price.
SELECT
    steam_app_id,
    itad_game_id,
    shop_id,
    shop_name,
    observed_at,
    price_amount,
    price_amount_int,
    regular_amount,
    regular_amount_int,
    discount_pct,
    currency
FROM renamed
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY itad_game_id, shop_id, observed_at
    ORDER BY fetched_at_utc DESC, (price_amount = 0 AND discount_pct = 0), discount_pct DESC, price_amount
) = 1
