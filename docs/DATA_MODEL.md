# Data model

dbt project `game_market/`, built into one DuckDB file (`data/game_market.duckdb`). The Streamlit dashboard
(`dashboard/`) reads it read-only, or the public snapshot built from it ([DATA_SOURCES.md](DATA_SOURCES.md)).

## Layers

```
S3 raw (landing) ──> staging ──> intermediate ──> marts (gold) ──> reporting ──> dashboard Q1–Q4
                        │             │               │                        dashboard Market overview,
                        │             │               └──────────────────────> Game explorer (analyst use of gold)
                   seeds (tracked_games, manual_id_overrides, seed_steam_release_context)

Postgres logs (ingestion_log, pipeline_run_log, dbt_node_result; read-only attach `ops`) ──> staging stg_ops__*
observability (game_coverage, mart_pipeline_health, mart_pipeline_stage_runs, mart_ingestion_daily,
mart_dbt_run_history) reads any layer, nothing reads it
```

| Layer | Folder | DuckDB schema | Materialization | Bronze/silver/gold | What it does |
|---|---|---|---|---|---|
| Landing | S3 `raw/…` | — | JSON / CSV / Parquet files | landing | API responses as fetched, append-only |
| Staging | `models/staging/` | `staging` | view | bronze | One model per source entity (`stg_<source>__<entity>`): parse, type, rename, dedup to the source grain. No business logic. |
| Intermediate | `models/intermediate/` | `intermediate` | table | silver | Where the logic lives (`int_*`): tracked-games scope, daily aggregation, spines, forward-fill, source merges, discount episodes. |
| Marts | `models/marts/core/` | `marts` | table | gold | General-purpose `dim_game` and `fact_*` at clear grains, with keys and tests. Thin: no question-specific logic. |
| Reporting | `models/reporting/` | `reporting` | table | consumption | `rpt_*` models per dashboard question (Q1–Q4). |
| Observability | `models/observability/` | `observability` | tables `game_coverage`, `mart_ingestion_daily`; views `mart_pipeline_health`, `mart_pipeline_stage_runs`, `mart_dbt_run_history`; all tagged `observability` (excluded in analytics-only builds) | — | Is the data complete and the pipeline healthy? ([PIPELINE.md](PIPELINE.md#observability)) |
| Seeds | `seeds/` | `seeds` | table | — | Human-curated inputs. |

Schema names are used exactly as configured (`macros/generate_schema_name.sql`), not dbt's default `main_staging`
and so on.

**Materialization.** DuckDB has no materialized views, so reporting models (and marts) are tables rebuilt by every
`dbt build`. Staging stays as views over the S3 files so each build reads the current raw data.

## May read

| Layer | May read | Never reads |
|---|---|---|
| staging | sources, seeds | anything else |
| intermediate | staging, seeds, other `int_*` | marts, reporting, observability |
| marts | intermediate, staging, seeds; `dim_game` (see below) | reporting, observability |
| reporting | marts (`dim_game`, `fact_*`); other `rpt_*` models of the same question (rollups such as a typical curve) | staging, intermediate, seeds, observability |
| observability | any layer | — (only exposures may point at it) |
| dashboard | `reporting.rpt_*` (Q1–Q4 question models), `marts.*` (gold), `observability.*` (Pipeline health page) | staging, intermediate |

The one reference inside marts: facts join `dim_game` for `game_key` (a star-schema join; it adds no logic). No
model reads reporting except observability, and no model reads observability.

## Scope: which games

`int_tracked_games` is the single definition: `tracked_games` seed rows that also have Steam appdetails.
`dim_game` and every intermediate model inner-join it. `is_active` in the seed steers ingestion only; inactive games
keep their history. A seed game without appdetails would be out of scope; currently all 55 seed games have them.

## Models

| Layer | Model | Grain | Key columns |
|---|---|---|---|
| intermediate | `int_tracked_games` | game | |
| intermediate | `int_player_activity_monthly__merged` | game × month (SteamCharts first, Kaggle only for months SteamCharts lacks) | |
| intermediate | `int_player_activity_daily` | game × UTC day | |
| intermediate | `int_price_daily` | game × day, Steam price, forward-filled | |
| intermediate | `int_sale_episodes` | Steam discount period | |
| intermediate | `int_ops__source_latest_data` | monitored data source: newest data timestamp in the warehouse | |
| staging | `stg_ops__ingestion_log`, `stg_ops__pipeline_run_log`, `stg_ops__dbt_node_result` | Postgres log rows, read at query time (views) | |
| marts | `dim_game` | game. Includes `steam_release_context` and `steam_release_context_note` from `seed_steam_release_context` (null = original launch) | `steam_app_id`, `name`, `release_date`, `steam_genres`, `developers`, `publishers`, `review_positivity_pct` |
| marts | `fact_player_activity` | game × reading (5-minute backfill and hourly collection) | `recorded_at`, `player_count`, `data_resolution` |
| marts | `fact_player_activity_daily` | **game × UTC day** (key `activity_day_key` = md5(steam_app_id, activity_date)); avg/peak/min players, completeness | `activity_date`, `avg_players`, `peak_players`, `data_resolution`, `is_complete_day` |
| marts | `fact_player_activity_monthly` | game × month | `activity_month`, `avg_players`, `peak_players`, `source` |
| marts | `fact_price_daily` | **game × day of Steam price** (shop 61, forward-filled between ITAD events; key `price_day_key` = md5(steam_app_id, price_date)) | `price_date`, `price_amount`, `regular_amount`, `discount_pct`, `is_on_sale` |
| marts | `fact_discount_episode` | **one Steam discount period per game** (consecutive discounted days; key `sale_episode_key` = md5(steam_app_id, sale_start)) | `sale_start`, `sale_end`, `sale_days`, `max_discount_pct` |
| marts | `fact_price_snapshot` | ITAD price event (all shops) | `observed_at`, `shop_id`, `price_amount`, `discount_pct` |
| marts | `fact_reviews`, `fact_critic_review` | review | `voted_up`, `playtime_at_review_minutes`, `review_created_at` (Steam reviews) |
| reporting | `rpt_game_lifecycle` | game (Q1 life after launch); includes `lowest_after_launch_players` | |
| reporting | `rpt_lifecycle_curve` | game × month since release (0–24), % of launch peak | |
| reporting | `rpt_lifecycle_typical_curve` | month since release: median across settled games, n_games, plateau | |
| reporting | `rpt_activity_health` | game (Q2 activity health) | |
| reporting | `rpt_discount_effect` | Steam discount period (Q3 do discounts bring players) | |
| reporting | `rpt_discount_effect_daily` | valid discount × UTC day (14 days before to 28 after), vs. its own pre-discount baseline | |
| reporting | `rpt_discount_typical` | discount group × phase: median lift pooled across discounts | |
| reporting | `rpt_discount_by_depth` | discount depth bucket (< 50%, 50–74%, ≥ 75% off): median lift during the discount | |
| reporting | `rpt_market_anomalies` | game × UTC day (Q4 unusual days); includes the z-score baseline (`baseline_log_mean`, `baseline_log_stddev`, `baseline_players`, `band_lower_players`, `band_upper_players`) and `avg_players` | |
| observability | `game_coverage` | seed game: what each game received, and why it is in or out of Q1–Q4 | |
| observability | `mart_pipeline_health` (view) | pipeline component: last success/attempt, status, error, hours since success, ok/warn/fail | |
| observability | `mart_pipeline_stage_runs` (view) | daily-flow run × stage (`pipeline_run_log` pass-through for the dashboard) | |
| observability | `mart_ingestion_daily` | monitored source × UTC day: attempts, successes, failures, expected, completeness | |
| observability | `mart_dbt_run_history` (view) | dbt invocation of the daily flow: models ok/error, tests pass/warn/fail, overall status | |

Metric formulas, baselines and N: [ANALYTICS.md](ANALYTICS.md).

## Querying the models

- Start with `marts` (`dim_game` plus the facts); `reporting` holds the ready-made answers to Q1–Q4; `staging` and
  `intermediate` are internals.
- Days are **UTC** days everywhere.
- Player data comes at three resolutions (`5min`, `hourly`, `monthly`). Do not average across them in one query:
  filter on `data_resolution`, or use the monthly table.
- For daily player facts, filter `is_complete_day` (at least 80% of the expected readings), or a half-collected day
  looks like a drop.
- A missing player count means unknown, not zero. The models drop those rows; do not turn them into zeros.
- Join names through `dim_game` on `steam_app_id`.
- "Sale" in column names (`is_on_sale`, `sale_start`, `sale_discount_pct`) means a Steam discount period, not units
  sold.
- Reviews are the newest 1,000 per game plus everything fetched since; reviews before 2026-09-28 are a
  helpfulness-ordered sample.
- What you find are associations. A discount coinciding with more players is not evidence that the discount caused it.

## Tests

Totals from `target/manifest.json` (dbt 1.12.5, `dbt parse` on 2026-10-07): **192 tests**, 190 severity error and 2
severity warn.

| Layer | Tests |
|---|---|
| Sources | 2 |
| Seeds | 16 |
| Staging | 37 |
| Intermediate | 14 |
| Marts (gold) | 59 |
| Reporting | 41 |
| Observability | 22 |
| Singular | 1 (`tests/assert_pipeline_health_rules.sql`, tag `observability`: the health rules in [PIPELINE.md](PIPELINE.md#health-rules-observabilitymart_pipeline_health)) |

- **Relationship tests:** 8 (7 facts → `dim_game.game_key`, 1 seed → `tracked_games`).
- **Conditional tests (`where`):** 3, marked below.
- **Not used:** source freshness, model contracts, `store_failures`, unit tests.

Abbreviations: nn = not_null, uq = unique, av = accepted_values, ar = dbt_utils.accepted_range,
ucc = dbt_utils.unique_combination_of_columns, rel = relationships. Severity is **error** unless stated.

| Layer | Model | Column | Tests |
|---|---|---|---|
| Sources | `steam_raw.app_details` | `steam_app_id` | nn |
| Sources | `opencritic_raw.reviews` | `steam_app_id` | nn |
| Seeds | `tracked_games` | `steam_app_id` | nn, uq |
| Seeds | `tracked_games` | `game_name`, `is_active` | nn each |
| Seeds | `manual_id_overrides` | (`steam_app_id`, `source`) | ucc |
| Seeds | `manual_id_overrides` | `steam_app_id` | nn; rel → `tracked_games.steam_app_id` (**warn**) |
| Seeds | `manual_id_overrides` | `source` | nn; av (`itad`, `opencritic`) |
| Seeds | `manual_id_overrides` | `status` | nn; av (`matched_manual`, `matched_imported`, `no_coverage`) |
| Seeds | `manual_id_overrides` | `source_game_id` | nn where `status in ('matched_manual', 'matched_imported')` |
| Seeds | `seed_steam_release_context` | `steam_app_id` | nn, uq |
| Seeds | `seed_steam_release_context` | `steam_release_context` | nn; av (`later_steam_release`, `rerelease`) |
| Staging | `stg_itad__price_history` | (`itad_game_id`, `shop_id`, `observed_at`) | ucc |
| Staging | `stg_kaggle__steamcharts_monthly` | (`steam_app_id`, `activity_month`) | ucc |
| Staging | `stg_opencritic__reviews` | `review_id` | nn, uq |
| Staging | `stg_opencritic__reviews` | `steam_app_id`, `published_at`, `outlet_id` | nn each |
| Staging | `stg_opencritic__reviews` | `np_score` | nn; ar 0–100 |
| Staging | `stg_ops__dbt_node_result` | (`invocation_id`, `unique_id`) | ucc |
| Staging | `stg_ops__dbt_node_result` | `status` | nn; av (`success`, `error`, `pass`, `fail`, `warn`, `skipped`, `no-op`) |
| Staging | `stg_ops__ingestion_log` | `logged_at` | nn |
| Staging | `stg_ops__ingestion_log` | `component` | av (`hourly_player_counts`, `prices`, `app_details`, `reviews`, `steamcharts_monthly`) |
| Staging | `stg_ops__pipeline_run_log` | (`run_id`, `stage`) | ucc |
| Staging | `stg_ops__pipeline_run_log` | `status` | nn; av (`running`, `success`, `failed`, `skipped`) |
| Staging | `stg_source_id_mapping` | (`steam_app_id`, `source`) | ucc |
| Staging | `stg_source_id_mapping` | `status` | nn; av (`matched_auto`, `matched_manual`, `matched_imported`, `no_coverage`, `not_found`) |
| Staging | `stg_source_id_mapping` | `source_game_id` | nn where `status in ('matched_auto', 'matched_manual', 'matched_imported')` |
| Staging | `stg_steam__app_details` | `steam_app_id` | nn, uq |
| Staging | `stg_steam__app_list` | `steam_app_id` | nn, uq |
| Staging | `stg_steam__app_list` | `app_name` | nn |
| Staging | `stg_steam__player_counts` | (`steam_app_id`, `recorded_at`) | ucc |
| Staging | `stg_steam__player_counts` | `steam_app_id`, `player_count`, `recorded_at` | nn each |
| Staging | `stg_steam__reviews` | (`steam_app_id`, `recommendation_id`) | ucc |
| Staging | `stg_steam__reviews` | `recommendation_id` | nn |
| Staging | `stg_steam__reviews_summary` | `steam_app_id` | nn, uq |
| Staging | `stg_steamcharts__monthly` | (`steam_app_id`, `activity_month`) | ucc |
| Staging | `stg_steamcharts__monthly` | `steam_app_id`, `activity_month` | nn each |
| Intermediate | `int_tracked_games` | `steam_app_id` | nn, uq |
| Intermediate | `int_player_activity_daily` | (`steam_app_id`, `activity_date`) | ucc |
| Intermediate | `int_player_activity_monthly__merged` | (`steam_app_id`, `activity_month`) | ucc |
| Intermediate | `int_player_activity_monthly__merged` | `source` | av (`steamcharts`, `kaggle`) |
| Intermediate | `int_price_daily` | (`steam_app_id`, `price_date`) | ucc |
| Intermediate | `int_price_daily` | `price_amount` | nn; ar min 0 |
| Intermediate | `int_price_daily` | `discount_pct` | ar 0–100 |
| Intermediate | `int_sale_episodes` | `sale_episode_key` | nn, uq |
| Intermediate | `int_sale_episodes` | `sale_days` | ar min 1 |
| Intermediate | `int_ops__source_latest_data` | `component` | nn, uq |
| Marts | `dim_game` | `game_key`, `steam_app_id` | nn, uq each |
| Marts | `dim_game` | `name` | nn |
| Marts | `dim_game` | `review_positivity_pct` | ar 0–100 where not null |
| Marts | `fact_player_activity` | `activity_key` | nn, uq |
| Marts | `fact_player_activity` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_player_activity` | `steam_app_id`, `player_count`, `recorded_at` | nn each |
| Marts | `fact_player_activity` | `data_resolution` | nn; av (`hourly`, `5min`, `monthly`) |
| Marts | `fact_player_activity_daily` | (`steam_app_id`, `activity_date`) | ucc |
| Marts | `fact_player_activity_daily` | `activity_day_key` | nn, uq |
| Marts | `fact_player_activity_daily` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_player_activity_monthly` | `activity_monthly_key` | nn, uq |
| Marts | `fact_player_activity_monthly` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_player_activity_monthly` | `steam_app_id`, `activity_month` | nn each |
| Marts | `fact_player_activity_monthly` | `source` | nn; av (`steamcharts`, `kaggle`) |
| Marts | `fact_price_snapshot` | `snapshot_id` | nn, uq |
| Marts | `fact_price_snapshot` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_price_snapshot` | `steam_app_id`, `shop_id`, `observed_at`, `price_amount`, `discount_pct` | nn each |
| Marts | `fact_price_snapshot` | `is_on_sale` | nn; av (true, false) |
| Marts | `fact_price_daily` | (`steam_app_id`, `price_date`) | ucc |
| Marts | `fact_price_daily` | `price_day_key` | nn, uq |
| Marts | `fact_price_daily` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_discount_episode` | (`steam_app_id`, `sale_start`) | ucc |
| Marts | `fact_discount_episode` | `sale_episode_key` | nn, uq |
| Marts | `fact_discount_episode` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_reviews` | `review_key` | nn, uq |
| Marts | `fact_reviews` | `game_key` | rel → `dim_game.game_key` |
| Marts | `fact_critic_review` | `critic_review_key` | nn, uq |
| Marts | `fact_critic_review` | `game_key` | nn; rel → `dim_game.game_key` |
| Marts | `fact_critic_review` | `np_score` | nn; ar 0–100 |
| Marts | `fact_critic_review` | `published_at` | nn |
| Reporting | `rpt_game_lifecycle` | `game_key` | nn, uq |
| Reporting | `rpt_game_lifecycle` | `lifecycle_status` | nn; av (`launch_observed`, `launch_not_observed`, `no_monthly_data`, `no_release_date`, `released_after_coverage`) |
| Reporting | `rpt_game_lifecycle` | `steam_release_context` | nn; av (`original_launch`, `later_steam_release`, `rerelease`) |
| Reporting | `rpt_game_lifecycle` | `launch_type` | av (`fresh_launch`, `pre_release_base`) |
| Reporting | `rpt_game_lifecycle` | `lifecycle_pattern` | av (`front_loaded`, `gradual_decline`, `sustained`, `growing`, `insufficient_history`) |
| Reporting | `rpt_game_lifecycle` | `retention_m12`, `lowest_vs_launch_peak` | ar min 0 each |
| Reporting | `rpt_lifecycle_curve` | (`steam_app_id`, `month_index`) | ucc |
| Reporting | `rpt_lifecycle_curve` | `vs_launch_peak` | nn |
| Reporting | `rpt_lifecycle_typical_curve` | `month_index` | nn, uq |
| Reporting | `rpt_lifecycle_typical_curve` | `n_games` | nn |
| Reporting | `rpt_activity_health` | `game_key` | nn, uq |
| Reporting | `rpt_activity_health` | `health_class` | nn; av (`declining`, `growing`, `stable`, `volatile`, `too_recent`, `insufficient_history`, `no_monthly_data`) |
| Reporting | `rpt_activity_health` | `size_tier` | av (`small`, `medium`, `large`, `very_large`) |
| Reporting | `rpt_activity_health` | `months_in_window` | ar 0–12 |
| Reporting | `rpt_discount_effect` | `sale_episode_key` | nn, uq |
| Reporting | `rpt_discount_effect` | `episode_status` | nn; av (`valid`, `no_activity_data`, `baseline_contaminated`, `insufficient_baseline`, `insufficient_during`, `insufficient_post`) |
| Reporting | `rpt_discount_effect` | `sale_outcome` | av (`no_lift`, `returned_to_baseline`, `elevated_after`, `below_baseline_after`) |
| Reporting | `rpt_discount_effect_daily` | `episode_day_key` | nn, uq |
| Reporting | `rpt_discount_effect_daily` | `phase` | av (`before`, `during`, `first_week_after`, `weeks_2_4_after`) |
| Reporting | `rpt_discount_typical` | (`discount_group`, `phase`) | ucc |
| Reporting | `rpt_discount_typical` | `phase` | av (the same four phases) |
| Reporting | `rpt_discount_by_depth` | `depth_bucket` | nn, uq; av (`under_50`, `50_to_74`, `75_or_more`) |
| Reporting | `rpt_discount_by_depth` | `n_discounts` | nn |
| Reporting | `rpt_market_anomalies` | `anomaly_key` | nn, uq |
| Reporting | `rpt_market_anomalies` | `anomaly_status` | nn; av (`scored`, `insufficient_baseline`) |
| Reporting | `rpt_market_anomalies` | `direction` | av (`spike`, `drop`) |
| Reporting | `rpt_market_anomalies` | `is_market_wide` | nn |
| Observability | `game_coverage` | `steam_app_id` | nn, uq |
| Observability | `game_coverage` | `in_dim_game` | av (true) (**warn**) |
| Observability | `mart_pipeline_health` | `component` | nn, uq; av (`hourly_player_counts`, `prices`, `app_details`, `reviews`, `steamcharts_monthly`, `dbt_build`) |
| Observability | `mart_pipeline_health` | `health_status` | nn; av (`ok`, `warn`, `fail`) |
| Observability | `mart_pipeline_health` | `last_status` | nn; av (`success`, `partial`, `failed`, `skipped`, `running`, `never_run`) |
| Observability | `mart_ingestion_daily` | (`component`, `activity_date`) | ucc |
| Observability | `mart_ingestion_daily` | `component`, `activity_date`, `completeness_pct` | nn each |
| Observability | `mart_dbt_run_history` | `invocation_id` | nn, uq |
| Observability | `mart_dbt_run_history` | `overall_status` | nn; av (`success`, `warn`, `failed`) |
| Observability | `mart_pipeline_stage_runs` | (`run_id`, `stage`) | ucc |
| Observability | `mart_pipeline_stage_runs` | `stage` | nn |
| Observability | `mart_pipeline_stage_runs` | `status` | nn; av (`success`, `failed`, `skipped`, `running`) |

## Rows dropped or filtered

No quarantine or error tables: rows are filtered out in SQL, and nothing is written aside.

### In dbt

| Model | What is dropped | Why |
|---|---|---|
| `stg_steam__player_counts` | rows with `player_count is null` (hourly and backfill) | Steam returned no value |
| `stg_steam__player_counts` | duplicate (game, timestamp) rows | append-only raw; an hourly reading wins over the 5-minute backfill, then the latest file |
| `stg_steam__app_details` | files with `data is null`; older fetches per game | latest fetch wins |
| `stg_steam__app_list` | `appid` null, `name` null or blank | — |
| `stg_steam__reviews` | reviews with null `recommendationid`; repeated reviews (older fetches and repeats across pages, about 13% of rows on 2026-09-28) | Steam's cursor pagination repeats reviews; latest fetch wins |
| `stg_steam__reviews_summary` | older fetches per game | latest fetch wins |
| `stg_opencritic__reviews` | non-English reviews (`language <> 'en-us'`) and reviews with null `np_score` | English reviews only; no usable score |
| `stg_itad__price_history` | older fetches and same-instant duplicates | every run re-fetches the full history; deterministic tie-break |
| `stg_kaggle__steamcharts_monthly` | `steam_appid is null` | — |
| `stg_steamcharts__monthly` | `month_label = 'Last 30 Days'`; older fetches per game-month | rolling window, not a calendar month; latest fetch wins |
| `stg_source_id_mapping` | ITAD resolutions with `status = 'error'` | a failed lookup must not hide the last good resolution |
| `int_tracked_games` and every inner join to it or to `dim_game` | seed games without Steam appdetails, and all data of games outside the seed | scope (for example, ITAD history of Dying Light, 239140, stays in raw) |
| `int_price_daily` | non-Steam shops (`shop_id <> 61`); all but the last event of a day; spine days with null `price_amount` | Steam price only; one row per game per day |
| `int_player_activity_monthly__merged` | Kaggle months that SteamCharts also has | SteamCharts has priority |
| `rpt_activity_health`, `rpt_game_lifecycle`, `rpt_discount_effect`, `rpt_market_anomalies` | null or zero `avg_players`; for Q3 and Q4, days that are not complete 5-minute days (`is_complete_day`: at least 80% of the expected readings) | analysis rules |

**Unparseable dates are not dropped.** `stg_steamcharts__monthly` uses `try_strptime`, so an unparseable label becomes
a NULL `activity_month` and its `not_null` test fails the build. `dim_game.release_date` uses `try_strptime`, so the
game gets `lifecycle_status = 'no_release_date'` in `rpt_game_lifecycle`. `stg_kaggle__steamcharts_monthly` uses
`strptime`, so an unparseable value fails the query.

### In ingestion (before S3)

- `src/ingestion/steam_player_counts.py`: a game whose request still fails after the retries gets no record (logged
  `failed` in `ingestion_log`); a game without `player_count` in the response is written with an empty value and
  dropped in staging.
- `src/ingestion/steam_app_details.py`: Steam `success=false` → no file written, logged `skipped` (delisted or invalid).
- `src/ingestion/steamcharts_monthly.py`: HTTP 404 → no file, logged `not_found`.
