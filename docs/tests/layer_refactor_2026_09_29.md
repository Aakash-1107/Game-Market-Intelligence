# Layer refactor — 2026-09-29

Branch `refactor/dbt-layers`. The goal was a structural refactor: staging → intermediate → marts, with the dashboard
reading marts only. Every mart must be identical before and after. Result: **identical**. See `docs/DATA_MODEL.md`
for the resulting model.

## Baseline

- DB backup of the Sept 28 19:36 build: `data/game_market_pre_layers_2026-09-29.duckdb`.
- Reference fingerprint of that build: `fingerprint_ref_build_2026_09_28.{json,txt}` (cutoff 2026-09-28).
- Fresh baseline: `dbt build --threads 1` on the **unchanged** code against current S3. Result:
  `PASS=154 WARN=0 ERROR=0` (160 nodes). The earlier 157 included `int_game_first_observed` and its 2 tests,
  deleted in `ef652f1`. Fingerprint: `fingerprint_pre_layers_2026_09_29.{json,txt}` (cutoff 2026-09-29).

### New data since the Sept 28 build (same cutoff, 2026-09-28)

The 8-game player-count backfill landed in S3 after the Sept 28 build. PUBG, Skyrim SE, DOS2, HOI4, Stardew Valley,
Factorio, Slay the Spire and Dead Cells now have 5-minute history from 2017-12-14 (about 275k rows each).

| Relation | Sept 28 build | Fresh baseline |
|---|---:|---:|
| fact_player_activity | 5,846,906 | 8,062,302 |
| int_player_activity_daily | 21,176 | 28,960 |
| an_market_anomalies | 20,299 | 28,010 |
| an_sale_effect | 2,068 | 2,068 (content changed) |
| int_sale_episodes | 2,072 | 2,072 (content changed: open episodes run to `current_date`) |
| game_coverage | 55 | 55 (content changed) |

All other relations are unchanged. Staging views are not in this table because they read S3 at query time.

## Changes

- `int_tracked_games` (new): `tracked_games` seed ∩ `stg_steam__app_details`. `dim_game` uses it.
- `int_price_daily`: reads `stg_itad__price_history`. It reproduces the fact's dedup rule (a no-op, kept as a
  safeguard), `is_on_sale = discount_pct > 0` and the tracked-games scope. It keeps the shop 61 filter.
- `int_player_activity_daily`: reads `stg_steam__player_counts` joined to `int_tracked_games`.
- `int_player_activity_monthly__merged` (new): the SteamCharts-first / Kaggle-fallback merge, moved out of
  `fact_player_activity_monthly`. The fact now only adds keys.
- `mart_game_lifecycle` and `mart_activity_health` now read the merged int model instead of the monthly fact.
  They only used `steam_app_id`, `activity_month` and `avg_players`.
- Renames: `an_game_lifecycle` → `mart_game_lifecycle`, `an_activity_health` → `mart_activity_health`,
  `an_sale_effect` → `mart_discount_effect`, `an_market_anomalies` → `mart_market_anomalies`. No columns were renamed.
- `marts/monitoring/` → `marts/observability/` (`game_coverage`).
- Schemas `staging` / `intermediate` / `marts` / `seeds` via `macros/generate_schema_name.sql`. Staging stays views.
- Dashboard: every query uses `marts.<model>`. `src/ingestion/opencritic_id_resolution.py` reads `marts.dim_game`.
- Exposures: dropped `fact_critic_review` from the game explorer (no page queries it). Added
  `dashboard_how_the_data_is_built` for `6_Data.py`.
- `src/utils/fingerprint_models.py`: new `--schemas` (default `main`, so old reports stay reproducible),
  `--cutoff` and `--rename OLD=NEW`.

## Verification

1. **Build:** `PASS=160 WARN=0 ERROR=0 NO-OP=7` (167 nodes). That is 154 + 2 new models + 4 new tests
   (`int_tracked_games` unique/not_null, merged model grain and `source` accepted values). The 7th NO-OP is the new
   exposure. The 10 `MissingArgumentsPropertyInGenericTestDeprecation` warnings are pre-existing test syntax.
2. **Fingerprint:** `fingerprint_post_layers_2026_09_29.{json,txt}`, compared with the fresh baseline with old names
   mapped to new ones. **Every pre-existing model, staging view and seed is identical in row count and content.**
   The only differences: 2 new int models added, and `int_game_first_observed` and `source_id_mappings` gone
   (step 4).
3. **Layer checks:**
   - `dbt ls -s +path:models/intermediate`: intermediate and staging only.
   - `dbt ls -s +path:models/staging`: staging only.
   - Manifest scan: 0 backward edges. The mart-to-mart edges are only `* → dim_game` and
     `game_coverage → 4 analytics marts`.
4. **Schema `main` cleanup:** 29 leftover objects listed and dropped. `main` is now empty.
   - 10 views: all `stg_*`.
   - 19 tables: `an_activity_health`, `an_game_lifecycle`, `an_market_anomalies`, `an_sale_effect`, `dim_game`,
     `fact_critic_review`, `fact_player_activity`, `fact_player_activity_monthly`, `fact_price_snapshot`,
     `fact_reviews`, `game_coverage`, `int_game_first_observed`, `int_player_activity_daily`, `int_price_daily`,
     `int_sale_episodes`, `manual_id_overrides`, `seed_steam_release_context`, `source_id_mappings`,
     `tracked_games`.
   - The DB file is 455 MB because DuckDB doesn't return freed space. A fresh file or `COPY FROM DATABASE`
     would shrink it; this is optional.
5. **Dashboard:** all 7 pages rendered headless with Streamlit `AppTest`, with 0 data errors. The Overview page
   raises a `StreamlitPageNotFoundError` from `st.page_link` when run outside `st.navigation`; the old code does
   the same, so it's a test-harness artefact.
   - Headline figures, old code on the Sept 28 DB vs new code on the current DB:
     - Q1: identical.
     - Q2: identical (30 of 46 stable, 2 declining). The two names can appear in either order.
     - Q3: 119 → 174 measured discounts.
     - Q4: surges/drops 209/41 → 255/57, games 16 → 23, "12× → 13× more likely on a big-discount day".
   - The Q3/Q4 changes come from the backfill, not the refactor (see Baseline). **Slides with Q3/Q4 numbers need
     updating.**
6. **`dbt docs generate`:** OK. The catalog holds staging 10, intermediate 5, marts 11, seeds 3. The lineage has no
   backward edges (manifest scan in step 3).

## Follow-ups (not done tonight)

- `int_tracked_games` ignores `is_active`, as `dim_game` did (all 55 games are active). Filtering on it would be a
  behaviour change.
- Column renames (`is_on_sale`, `sale_start`, `sale_discount_pct` → discount wording).
- Hardcoded copy that no longer matches the data after the backfill: `dashboard/views/4_Market_Events.py` says
  "21 games" at lines 16 and 103. The 5-minute data now covers 29 games, and `6_Data.py` already computes that
  count.
- Q2 "declining" list order depends on query order; add an `order by` for a stable headline.
- A6 must be rerun on the same UTC day as the baseline. `int_price_daily` and `int_sale_episodes` extend to
  `current_date`.
