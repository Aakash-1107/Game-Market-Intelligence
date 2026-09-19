-- depends_on: {{ source('steam_raw', 'app_list') }}
with source as (

    select *
    from read_csv_auto('s3://game-market-raw/raw/steam/app_list/steam_app_list.csv')

),

renamed as (

    select
        appid::integer  as steam_app_id,
        name::varchar   as app_name

    from source

    where appid is not null
      and name is not null
      and trim(name) != ''

)

select * from renamed