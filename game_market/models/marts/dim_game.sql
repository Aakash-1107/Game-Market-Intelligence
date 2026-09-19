with app_list as (

    select
        steam_app_id,
        app_name

    from {{ ref('stg_steam__app_list') }}

),

final as (

    select
        md5(steam_app_id::varchar)  as game_key,
        steam_app_id,
        app_name

    from app_list

)

select * from final