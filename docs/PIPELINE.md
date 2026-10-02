# Pipeline

Two Prefect flows feed the warehouse; dbt turns the raw files into the models in `docs/DATA_MODEL.md`.

| Flow | Where it runs | Schedule | What it does |
|---|---|---|---|
| `hourly-steam-ingestion` (`First_data_ingest/steam_data_ingest.py`) | Prefect managed work pool | every hour (`0 * * * *`) | Current player count for every active game, written to S3 `raw/steam/player_counts/`; one `ingestion_log` row per game |
| `daily_market_refresh` (`flows/daily_market_refresh.py`) | the machine that holds `data/game_market.duckdb` (local run / `--serve`, 07:00 Europe/Berlin) | daily | resolve ITAD IDs → prices, Steam app details, Steam reviews, SteamCharts monthly (in parallel) → hourly-data freshness check → `dbt build` (only if everything before it succeeded) |

## Running dbt

The dbt profile is committed: **`game_market/profiles.yml`**. Every credential in it is an `env_var`: AWS keys and
region, `DUCKDB_PATH`, `DATABASE_URL`. The variables are listed in `.env.example`.

How dbt finds the profile and the variables:
- dbt checks the working directory before `~/.dbt`, so running from `game_market/` uses the repo profile. The daily
  flow passes `--profiles-dir game_market` explicitly. From anywhere else, use `--profiles-dir game_market` or
  `DBT_PROFILES_DIR=game_market`.
- dbt 1.12 loads `.env` itself: it searches upward from the working directory, finds the repo's `.env`, and
  lets variables already set in the shell win.

### Two modes

| Mode | Command (from `game_market/`) | Needs | Builds |
|---|---|---|---|
| **Full** (target `dev`, the default) | `dbt build` | S3 credentials **and** `DATABASE_URL` | everything, including the observability models |
| **Analytics only** (target `analytics`) | `dbt build --target analytics --exclude tag:observability` | S3 credentials only | staging → intermediate → marts → reporting, and the dashboard's analysis pages |

- The analytics side never depends on the log database:
  - target `analytics` has no Postgres attach;
  - every model that reads the logs is tagged `observability`: the `stg_ops__*` staging views,
    `int_ops__source_latest_data`, everything in `models/observability/`, and the Pipeline health exposure.
- The daily flow picks the mode itself. Full when the log database answers; otherwise analytics with a warning, and
  the run continues.
- The dashboard works the same way. Without `DATABASE_URL`, or with the database unreachable, only the Pipeline
  health page shows a message; every other page reads the local DuckDB file.

**Any Postgres works for the logs.** Production uses Neon. For reproduction a local Postgres is enough:
1. Point `DATABASE_URL` at it.
2. Create the tables with `psql "$DATABASE_URL" -f sql/ddl/ingestion_log.sql` and
   `-f sql/ddl/observability.sql`, or run `python -m src.observability.run_log --create`.

## Observability

The question it answers: **is the pipeline healthy right now, and if not, where did it fail?**

### Three layers of monitoring

| Layer | Answers | Where |
|---|---|---|
| Prefect Cloud | Did the flow run, and did its tasks finish? | Prefect UI (flow runs, task states, logs) |
| `ingestion_log` (Postgres) | Did each request succeed, per game? | one row per game per stage per script run, written by every ingestion script, including the hourly flow |
| Observability models (dbt) | Is the data healthy end to end? | `pipeline_run_log` + `dbt_node_result` + `ingestion_log`, turned into `observability.mart_pipeline_health`, `mart_ingestion_daily` and `mart_dbt_run_history`; dashboard page **Pipeline health** |

### What the daily flow logs

`src/observability/run_log.py`, tables in `sql/ddl/observability.sql`:

- **`pipeline_run_log`**: one row per flow run per stage: `resolve_ids`, `ingest_prices`, `ingest_app_details`,
  `ingest_reviews`, `ingest_steamcharts`, `freshness_check`, `dbt_build`.
  - Each stage writes `running`, then `success` or `failed` with `finished_at`, records in/out (games attempted /
    succeeded) and the error.
  - A stage that never ran because an upstream task failed is written as `skipped`, naming the failed stage.
  - `dbt_build` is `skipped` when the gate blocks it, with the reason.
- **`dbt_node_result`**: after every `dbt build` of the flow, passed or failed, one row per node, from
  `game_market/target/run_results.json`:
  - `metadata.invocation_id` and `metadata.generated_at`;
  - per result: `unique_id`, `status`, `execution_time`, `failures`, `message` and `adapter_response.rows_affected`
    (only seeds report it on DuckDB);
  - `resource_type` = the `unique_id` prefix.

  A `run_results.json` older than the build is not recorded; that happens when dbt stopped before writing one.
- Writes are upserts on the primary key: rerunning never duplicates rows.
- **Observability never breaks the pipeline.** Every write is wrapped: a failure becomes a Python `logging` warning
  and a Prefect log line, and the task carries on. A stage's own exception is re-raised unchanged.
- **Ingestion scripts behave the same way.** They write `ingestion_log` through `src/common/log_db.py`. A missing
  `DATABASE_URL`, an unreachable database or a failed insert prints one warning, and the ingestion continues.
  - The hourly flow already skipped the log without `DATABASE_URL` and guarded its connection, so it was left
    unchanged.

### How dbt reads the logs

Target `dev` attaches the log database read-only through DuckDB's `postgres` extension (alias `ops`). It is declared
as dbt source `ops` (`ingestion_log`, `pipeline_run_log`, `dbt_node_result`), and the `stg_ops__*` staging views
read it live. The dashboard makes the same read-only attach.

### Grouping runs: `ingestion_log.run_id` is per row

`ingestion_log.run_id` defaults to a random uuid **per row** (`sql/ddl/ingestion_log.sql`); the scripts do not pass
one. It identifies a log row, not a run, so the observability models group runs by time:

- **hourly source:** the clock hour of `run_timestamp`. One run per hour; the hourly completeness slot is
  (game, clock hour).
- **daily sources:** the UTC day of `run_timestamp`. The daily flow runs once a day; the slot is (game, UTC day).

The daily flow's own stages are grouped properly by the Prefect flow run id (`pipeline_run_log.run_id`).

### Health rules (`observability.mart_pipeline_health`)

A **view**, not a table: status is computed when it is read, against `now()`. A table built at dbt-build time would
keep saying "healthy" if builds stopped, which is exactly the failure it has to detect.

`mart_dbt_run_history` is a view for a related reason: a build's results are recorded only after it finishes, so a
table built by that build would always be one build behind.

| Component | Evidence | ok threshold (hours since last success) |
|---|---|---|
| `hourly_player_counts` | `ingestion_log` (steam / raw) | 2 h |
| `prices`, `app_details`, `reviews`, `steamcharts_monthly` | `ingestion_log` + the flow's stage rows | 26 h |
| `dbt_build` | `dbt_node_result` + the flow's `dbt_build` stage | 26 h |

Status, evaluated top to bottom:
1. **fail** when the component has never succeeded, its latest attempt failed, partly failed or was skipped, or
   (`dbt_build`) the latest recorded build had a model error or a failing test. Age does not matter here.
2. **warn** when the last success is older than the ok threshold.
3. **ok** otherwise.

Being late alone never makes a component `fail`; it stays `warn` however old the last success is. The rules are
checked by the singular test `tests/assert_pipeline_health_rules.sql` (tag `observability`).
- The latest attempt is the latest clock hour for hourly data and the latest UTC day for the daily sources; a flow
  stage row replaces it when it is newer.

`mart_ingestion_daily` gives completeness per source per UTC day:
- expected = active games × 24 (hourly) or × 1 (daily sources);
- days without any attempt are kept, at 0%;
- today is partial until the day ends.

`int_ops__source_latest_data` gives the newest data timestamp per source in the warehouse, as of the last build. It
comes from each staging model's fetch or ingest timestamp. Prices are the exception: they use the last successful
ITAD fetch in `ingestion_log`, because `stg_itad__price_history` does not expose its fetch timestamp.

### Gaps found while testing (fixed 2026-09-29)

- **An ITAD outage looked like success.** With an invalid ITAD key, `resolve_ids` resolved 0 of N games but
  succeeded, prices "succeeded" on zero games, and `dbt build` ran on stale prices. `resolve_ids` now fails when no
  game resolves at all; a partial miss only warns.
- **A task that never ran crashed the flow.** When `resolve_ids` failed, reading the prices task's result raised
  `UnfinishedRun`, so the flow crashed before its summary and before logging the skip. The flow now treats it as
  not run.

### Known limitations

- **The hourly flow is not instrumented stage by stage.** It runs on the managed pool and was deliberately left
  unchanged. Its health is inferred from `ingestion_log` (one row per game per hour) and data freshness.
- Only dbt builds run **by the daily flow** are recorded. A manual `dbt build` is not.
- `expected` uses today's active games, so days before a game was added read slightly below 100%.
