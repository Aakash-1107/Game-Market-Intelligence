# Data model

dbt project `game_market/`, built into one DuckDB file (`data/game_market.duckdb`). The Streamlit dashboard
(`dashboard/`) reads it read-only.

## Layers

```
S3 raw (landing) ──> staging ──> intermediate ──> marts (gold) ──> reporting ──> dashboard Q1–Q4
                        │             │               │                        dashboard Market overview,
                        │             │               └──────────────────────> Game explorer (analyst use of gold)
                   seeds (tracked_games, manual_id_overrides, seed_steam_release_context)

Neon logs (ingestion_log, pipeline_run_log, dbt_node_result; read-only attach `ops`) ──> staging stg_ops__*
observability (game_coverage, mart_pipeline_health, mart_ingestion_daily, mart_dbt_run_history) reads any layer,
nothing reads it
```

| Layer | Folder | DuckDB schema | Materialization | Bronze/silver/gold | What it does |
|---|---|---|---|---|---|
| Landing | S3 `raw/…` | — | JSON / CSV files | landing | API responses as fetched, append-only |
| Staging | `models/staging/` | `staging` | view | bronze | One model per source entity (`stg_<source>__<entity>`): parse, type, rename, dedup to the source grain. No business logic. |
| Intermediate | `models/intermediate/` | `intermediate` | table | silver | Where the logic lives (`int_*`): tracked-games scope, daily aggregation, spines, forward-fill, source merges, discount episodes. |
| Marts | `models/marts/core/` | `marts` | table | gold | General-purpose `dim_game` and `fact_*` at clear grains, with keys and tests. Thin: no question-specific logic. |
| Reporting | `models/reporting/` | `reporting` | table | consumption | One `rpt_*` model per dashboard question (Q1–Q4). |
| Observability | `models/observability/` | `observability` | table; `mart_pipeline_health` and `mart_dbt_run_history` are views; all tagged `observability` (excluded in analytics-only builds) | — | Is the data complete and the pipeline healthy? (`game_coverage`, pipeline health, daily ingestion completeness, dbt run history; see `docs/PIPELINE.md`) |
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
| dashboard | `reporting.rpt_*` (Q1–Q4 question models), `marts.*` (gold) | staging, intermediate |

The one reference inside marts: facts join `dim_game` for `game_key` (a star-schema join; it adds no logic). No
model reads reporting except observability, and no model reads observability.

## Scope: which games

`int_tracked_games` is the single definition: `tracked_games` seed rows that also have Steam appdetails.
`dim_game` and every intermediate model inner-join it. `is_active` in the seed steers ingestion only; inactive games
keep their history. A seed game without appdetails (Dying Light, 239140) is out of scope.

## Models

| Layer | Model | Grain |
|---|---|---|
| intermediate | `int_tracked_games` | game |
| intermediate | `int_player_activity_monthly__merged` | game × month (SteamCharts first, Kaggle fills gaps) |
| intermediate | `int_player_activity_daily` | game × UTC day |
| intermediate | `int_price_daily` | game × day, Steam price, forward-filled |
| intermediate | `int_sale_episodes` | Steam discount period |
| intermediate | `int_ops__source_latest_data` | monitored data source: newest data timestamp in the warehouse |
| staging | `stg_ops__ingestion_log`, `stg_ops__pipeline_run_log`, `stg_ops__dbt_node_result` | Neon log rows, read live (views) |
| marts | `dim_game` | game. Includes `steam_release_context` and `steam_release_context_note` from `seed_steam_release_context` (null = original launch) |
| marts | `fact_player_activity` | game × reading (5-min backfill + hourly live) |
| marts | `fact_player_activity_daily` | **game × UTC day** (key `activity_day_key` = md5(steam_app_id, activity_date)); avg/peak/min players, completeness |
| marts | `fact_player_activity_monthly` | game × month |
| marts | `fact_price_daily` | **game × day of Steam price** (shop 61, forward-filled between ITAD events; key `price_day_key` = md5(steam_app_id, price_date)) |
| marts | `fact_discount_episode` | **one Steam discount period per game** (consecutive discounted days; key `sale_episode_key` = md5(steam_app_id, sale_start)) |
| marts | `fact_price_snapshot` | ITAD price event (all shops) |
| marts | `fact_reviews`, `fact_critic_review` | review |
| reporting | `rpt_game_lifecycle` | game (Q1 life after launch); includes `lowest_after_launch_players` |
| reporting | `rpt_lifecycle_curve` | game × month since release (0–24), % of launch peak |
| reporting | `rpt_lifecycle_typical_curve` | month since release: median across settled games, n_games, plateau |
| reporting | `rpt_activity_health` | game (Q2 activity health) |
| reporting | `rpt_discount_effect` | Steam discount period (Q3 do discounts bring players) |
| reporting | `rpt_discount_effect_daily` | valid discount × UTC day (14 days before to 28 after), vs. its own pre-discount baseline |
| reporting | `rpt_discount_typical` | discount group × phase: median lift pooled across discounts |
| reporting | `rpt_market_anomalies` | game × UTC day (Q4 unusual days); includes the z-score baseline (`baseline_log_mean`, `baseline_log_stddev`, `baseline_players`, `band_lower_players`, `band_upper_players`) and `avg_players` |
| observability | `game_coverage` | seed game: what each game received, and why it is in or out of Q1–Q4 |
| observability | `mart_pipeline_health` (view) | pipeline component: last success/attempt, status, error, hours since success, ok/warn/fail |
| observability | `mart_ingestion_daily` | monitored source × UTC day: attempts, successes, failures, expected, completeness |
| observability | `mart_dbt_run_history` (view) | dbt invocation of the daily flow: models ok/error, tests pass/warn/fail, overall status |

Metric formulas, baselines and N: `docs/ANALYTICS.md`. All day-level models use UTC days.

Some column names still say "sale" (`is_on_sale`, `sale_start`, `sale_discount_pct`). In this project "sale" means a
Steam discount period, not units sold.
