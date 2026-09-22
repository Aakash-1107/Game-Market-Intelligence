{{ config(materialized='table') }}

with steam_prices as (

    select
        steam_app_id,
        cast(observed_at at time zone 'UTC' as date) as price_date,
        price_amount,
        regular_amount,
        discount_pct,
        is_on_sale,
        currency,
        row_number() over (
            partition by steam_app_id,
                         cast(observed_at at time zone 'UTC' as date)
            order by observed_at desc
        ) as rn

    from {{ ref('fact_price_snapshot') }}
    where shop_id = 61

),

-- one row per game per day: take the last event if multiple landed on same day
daily_events as (

    select
        steam_app_id,
        price_date,
        price_amount,
        regular_amount,
        discount_pct,
        is_on_sale,
        currency
    from steam_prices
    where rn = 1

),

-- date spine: one row per game per calendar day across its observed range
game_date_spine as (

    select
        g.steam_app_id,
        d.spine_date
    from (
        select distinct steam_app_id,
               min(price_date) over (partition by steam_app_id) as first_date
               
        from daily_events
    ) g
    cross join (
        select unnest(
            generate_series(
                (select min(price_date) from daily_events),
                current_date,
                interval '1 day'
            )
        )::date as spine_date
    ) d
    where d.spine_date between g.first_date and current_date
),

-- left join events onto spine, leaving NULLs where no event occurred
spine_with_events as (

    select
        s.steam_app_id,
        s.spine_date                    as price_date,
        e.price_amount,
        e.regular_amount,
        e.discount_pct,
        e.is_on_sale,
        e.price_date as event_date,
        e.currency
    from game_date_spine s
    left join daily_events e
        on s.steam_app_id = e.steam_app_id
        and s.spine_date  = e.price_date

),

-- forward-fill: carry last known value forward until next change event
forward_filled as (

    select
        steam_app_id,
        price_date,
        last_value(price_amount  ignore nulls) over w as price_amount,
        last_value(regular_amount ignore nulls) over w as regular_amount,
        last_value(discount_pct  ignore nulls) over w as discount_pct,
        last_value(is_on_sale    ignore nulls) over w as is_on_sale,
        last_value(event_date ignore nulls) over w as last_price_event_date,
        last_value(currency      ignore nulls) over w as currency
    from spine_with_events
    window w as (
        partition by steam_app_id
        order by price_date
        rows between unbounded preceding and current row
    )

)

select
    md5(steam_app_id || '|' || price_date::text) as price_day_key,
    steam_app_id,
    price_date,
    price_amount,
    regular_amount,
    discount_pct,
    is_on_sale,
    last_price_event_date,
    date_diff('day', last_price_event_date, price_date) as days_since_price_event,
    case
        when price_amount = 0 then 'free'
        when date_diff('day', last_price_event_date, price_date) <= 120 then 'recent'
        when date_diff('day', last_price_event_date, price_date) <= 400 then 'aging'
        else 'long_static'
    end as price_freshness,
    currency
from forward_filled
where price_amount is not null