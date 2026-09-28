# `game_source_mapping` (Neon): obsolete since 2026-09-28

Nothing reads this table any more. It's left in place in Neon and isn't dropped.

Until 2026-09-28 it held Steam App ID → ITAD UUID (55 rows) and Steam App ID → OpenCritic ID (12 rows). It was read by `itad_price_history.py` and `opencritic_reviews.py`, and written by `populate_itad_mapping.py` and `opencritic_id_resolution.py`. Both writers are also marked obsolete.

It was replaced as follows:

| Was | Now |
|---|---|
| ITAD UUIDs cached in Neon | `src/ingestion/resolve_ids.py` resolves every active game on every run → snapshot in S3 (`raw/mappings/itad/…`) + in memory for the price task |
| OpenCritic IDs in Neon | `game_market/seeds/manual_id_overrides.csv` (2 as `matched_manual`, 10 as `matched_imported`, copied on 2026-09-28) |
| Manual decisions scattered (Neon, `ingestion_log`, the deleted `source_id_mappings` seed) | `manual_id_overrides.csv`, always wins |
| dbt had no view of the mapping | `stg_source_id_mapping` (snapshot ∪ overrides), used by `game_coverage` |

Its structure, for reference: `steam_app_id integer, source text, source_game_id text, mapped_at timestamptz default now()`, with primary key `(steam_app_id, source)`.

It can be dropped once the new flow has run successfully for a while. That's Ash's call.
