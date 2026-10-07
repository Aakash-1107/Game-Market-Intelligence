# Observability layer (Part B) — 2026-09-29

> **Note (2026-10-07): names superseded.** The hourly flow `First_data_ingest/steam_data_ingest.py` is now
> `src/ingestion/steam_player_counts.py` and runs from GitHub Actions instead of the Prefect managed pool;
> `steam_review_histogram.py` and `opencritic_id_resolution.py` (with its table `game_source_mapping`) no longer exist.
> The backup `~/.dbt/profiles.yml.bak_2026-09-29` is local, not in the repository.

Goal: one queryable answer to "is the pipeline healthy right now, and if not, where did it fail?", without ever
breaking the pipeline. Design and rules: `docs/PIPELINE.md`.

## What was built

| Step | Result |
|---|---|
| B1 | `sql/ddl/observability.sql`: `pipeline_run_log` (PK run_id, stage) and `dbt_node_result` (PK invocation_id, unique_id), created in Neon |
| B2 | `src/observability/run_log.py` (`log_stage`, `log_skipped`, `record_dbt_results`, upserts). `flows/daily_market_refresh.py` logs all 7 stages; the hourly flow is unchanged |
| B3 | **Read-only attach** (DuckDB 1.5.5 `postgres` extension, alias `ops`), verified on Windows. Writes through the attach are rejected. It also works from a read-only DuckDB file (the dashboard). No Parquet fallback needed |
| B4 | `stg_ops__ingestion_log`, `stg_ops__pipeline_run_log`, `stg_ops__dbt_node_result` (views); `int_ops__source_latest_data`; `observability.mart_pipeline_health` (view), `mart_ingestion_daily` (table), `mart_dbt_run_history` (**view**, see deviations) |
| B5 | Dashboard page *Pipeline health* (`dashboard/views/7_Pipeline_Health.py`) + exposure `dashboard_pipeline_health` |
| Extra | Repo profile `game_market/profiles.yml` (targets `dev` / `analytics`), `tag:observability`, `src/common/log_db.py` for the ingestion scripts, flow fallback to the analytics build |

Fields taken from `run_results.json`, all read from the actual file (dbt 1.12.5, schema v6):
- `metadata.invocation_id` and `metadata.generated_at`;
- per result: `unique_id`, `status`, `execution_time`, `failures`, `message` and `adapter_response.rows_affected`
  (present only for seeds);
- `resource_type` = the `unique_id` prefix.
- `metadata.invocation_started_at` is used only to reject a stale file.

## Verification

### Builds
- **Full build, repo profile** (`dbt build --profiles-dir .`): `PASS=224 WARN=0 ERROR=0 NO-OP=8`. That is A3's 192 + 7
  models + 25 tests. The log shows `Concurrency: 1 threads (target='dev')` from the repo profile; `~/.dbt` says 4.
  `dbt debug` reports `Using profiles.yml file at .\profiles.yml`.
- **Analytics build without Neon** (`DATABASE_URL=` empty, `dbt build --target analytics --exclude tag:observability`):
  `PASS=188 WARN=0 ERROR=0`, target `analytics`.
  - dbt loads the repo `.env` by itself, so "unset" was tested as an empty override (`load_dotenv` never replaces a
    variable that is already set).
- **Part A models still identical:** `fingerprints/fingerprint_post_observability_2026_09_29.*` vs the A3 result, with
  `--cutoff "2026-09-29 17:17:48+00"` and the same dropped columns. Every existing relation is identical; the only
  differences are the 7 new observability relations. This was taken before any flow run, because the test runs below
  fetched new data for 2 games.

### Sanity check: hourly completeness (`mart_ingestion_daily`)

| Day | Completeness | Known history |
|---|---|---|
| 14 Sep | 12.5% | ramp-up |
| 15 Sep | 45.8% | ramp-up |
| 16–17 Sep | 100% / 79.2% | |
| 18 Sep | **0%** | collector outage (no rows; kept by the date spine) |
| 19 Sep | **50.0%** | partial |
| 20–25 Sep | 95.8–100% | |
| 26–28 Sep | 98.2% | 54 of 55 games before Hades was added |

### Daily flow runs (subset: Stardew Valley 413150, Hades 1145360)

A full 55-game run was not needed to exercise the logging path. The subset runs make today's daily sources read
3.6% (2 / 55).

1. **Normal run:** all 7 stages logged `success` with records in/out (2/2; dbt 224/224); 232 rows in
   `dbt_node_result`; `mart_pipeline_health` all 6 components `ok`.
2. **Rerun of the logger** on the same `run_results.json`: 232 rows written again, table still 232 rows = 232
   distinct keys. `pipeline_run_log`: rows = distinct (run_id, stage). **No duplicates.**
3. **Simulated failure:** `ITAD_API_KEY=invalid`, set in the process environment only; `.env` was untouched.
   - First attempt: **the pipeline did not notice.** `resolve_ids` resolved 0 of 2 but succeeded, prices
     "succeeded" on 0 games, and dbt built. Fixed (see gaps).
   - After the fixes:
     - `resolve_ids` is `failed`: "none of 2 game(s) resolved to an ITAD ID (check ITAD_API_KEY / ITAD availability)".
     - `ingest_prices` is `skipped`: "not run: upstream failed (resolve_ids)".
     - `dbt_build` is `skipped`: "upstream failed: resolve_ids, ingest_prices".
     - The other stages succeed, and the flow ends as Failed with its summary.
   - `mart_pipeline_health`: prices **warn / skipped** and dbt_build **warn / skipped**, with those errors; the
     dashboard shows "2 of 6 components need attention".
4. **Log database unreachable** (`DATABASE_URL` pointing at a refused port, 1 game): the flow completed. All
   ingestion stages succeeded, every log write warned instead of failing (45 warnings), and dbt fell back to target
   `analytics` without observability (`PASS=188`).

### Ingestion scripts without a log database

Every script in `src/ingestion/` was checked.

- **8 needed changes.** They crashed on import (`os.environ["DATABASE_URL"]` → `KeyError`) or at start
  (unguarded `psycopg2.connect`):
  - `backfill_player_counts`, `itad_price_history`, `opencritic_reviews`, `resolve_ids`
  - `steam_app_details`, `steam_review_histogram`, `steam_reviews`, `steamcharts_monthly`

  They now use `src/common/log_db.connect_log_db()`, which warns and returns a no-op connection. A failed insert
  mid-run also only warns. Tested: all 8 import with `DATABASE_URL` empty, and empty or unreachable URLs give one
  warning and no exception.
- **Unchanged:**
  - `First_data_ingest/steam_data_ingest.py` (hourly flow; ground rule) already skips the log without
    `DATABASE_URL` and guards its connection.
  - `opencritic_id_resolution.py` is obsolete and in no flow. Its output is the Postgres table
    `game_source_mapping`, so it still requires the database.

### Dashboard

All 8 pages were rendered headless in three runs: `DATABASE_URL` empty, unreachable, and normal.
- **Without Neon:** pages 0–6 render with their normal headlines. Only Pipeline health shows "The pipeline logs
  live in Neon and could not be reached …".
- **Normal:** Pipeline health renders:
  - status tiles;
  - "Hourly collection: lowest day 18 Sep at 0%";
  - the 2 recorded dbt builds.

## Gaps found and fixed in the daily flow

1. **ITAD outage reported as success.** `resolve_ids` now fails when no game resolves (a partial miss only warns).
   Before, a bad key or an ITAD outage let `dbt build` run on stale prices.
2. **Crash when a task never ran.** `fut.result(raise_on_failure=False)` raises `UnfinishedRun` for a `NotReady`
   task, so any `resolve_ids` failure crashed the flow before its summary. It is now caught and logged as skipped.

## Deviations from the handoff

- `mart_dbt_run_history` is a **view**, not a table. A build's results are recorded only after it finishes, so the
  table could never contain its own build and would always be one build behind.
- Observability models live in `models/observability/` (schema `observability`), as requested; not in
  `marts/observability`.
- A component is at least `warn` when its latest attempt failed, partly failed or was skipped, even if the last
  success is recent. Without this rule the failure simulation would still show `ok`.
- `ingestion_log.run_id` is a per-row uuid, so runs are grouped by clock hour (hourly) / UTC day (daily).
- `int_ops__source_latest_data`: prices use the last successful ITAD fetch in `ingestion_log`, because
  `stg_itad__price_history` exposes no fetch timestamp. `stg_itad__price_history` itself is unchanged.
- `~/.dbt/profiles.yml` was edited during B3 (backup: `~/.dbt/profiles.yml.bak_2026-09-29`); it is no longer used.
- `game_market/.user.yml` (written by dbt next to the profile) is gitignored.

## Not done

- A full 55-game daily run. The subset runs exercise every logging path; the next scheduled run fills today.
- Stage-level instrumentation of the hourly flow (ground rule); its health comes from `ingestion_log`.
