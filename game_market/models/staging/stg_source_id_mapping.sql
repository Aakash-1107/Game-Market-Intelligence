-- Grain: one row per (steam_app_id, source). Source IDs per game, replacing the obsolete Neon table game_source_mapping.
--   itad:       latest automatic resolution per game (resolve_ids.py snapshots in S3), ignoring transient errors
--   any source: rows in the manual_id_overrides seed always win (OpenCritic comes only from here)

with snapshots as (

    select
        resolved_at_utc::timestamptz                as resolved_at,
        unnest(mappings)                            as m
    from {{ source('mappings_raw', 'itad_mapping') }}

),

itad_resolved as (

    select
        m.steam_app_id::integer                     as steam_app_id,
        'itad'                                      as source,
        m.itad_game_id::varchar                     as source_game_id,
        m.status::varchar                           as status,
        resolved_at
    from snapshots
    where m.status <> 'error'   -- a failed lookup must not hide the last good resolution
    qualify row_number() over (
        partition by m.steam_app_id
        order by resolved_at desc
    ) = 1

),

overrides as (

    select
        cast(steam_app_id as integer)               as steam_app_id,
        lower(source)                               as source,
        nullif(source_game_id, '')                  as source_game_id,
        status,
        cast(null as timestamptz)                   as resolved_at
    from {{ ref('manual_id_overrides') }}

),

combined as (

    select steam_app_id, source, source_game_id, status, resolved_at, 1 as priority from overrides
    union all
    select steam_app_id, source, source_game_id, status, resolved_at, 2 as priority from itad_resolved

)

select
    steam_app_id,
    source,
    source_game_id,
    status,
    priority = 1                                    as is_manual_override,
    resolved_at
from combined
qualify row_number() over (
    partition by steam_app_id, source
    order by priority
) = 1
