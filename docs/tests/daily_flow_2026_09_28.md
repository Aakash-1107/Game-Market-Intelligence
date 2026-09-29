# Step 4: `daily_market_refresh` flow (2026-09-28)

## What it is

One Prefect flow, [flows/daily_market_refresh.py](../../flows/daily_market_refresh.py).

```powershell
python flows/daily_market_refresh.py            # all active games
python flows/daily_market_refresh.py 1145360    # only these games
python flows/daily_market_refresh.py --serve    # local scheduler, daily 07:00 Europe/Berlin (second priority, see below)
```

- **Runs locally and reports to Prefect Cloud.** This machine's only Prefect profile is *named* `ephemeral`, but it contains a Prefect Cloud `PREFECT_API_URL` and `PREFECT_API_KEY`. So every run on 2026-09-28 was registered in Prefect Cloud: the log prints a "View at https://app.prefect.cloud/…" link. No local server is started.
  - Without such a profile, Prefect 3 falls back to a temporary local server, so the one-command run doesn't depend on Cloud.
  - (An earlier draft of this report said the runs used a local temporary server. That was wrong.)
- **Stop the Streamlit dashboard first.** dbt needs the write lock on `data/game_market.duckdb`. The flow checks the lock before running dbt and fails with a clear message if the file is locked.

| # | Task | Notes |
|---|---|---|
| 1 | `load_active_games` | active rows of `tracked_games.csv`, or the games given on the command line |
| 2 | `resolve_ids` | ITAD UUIDs (seed + lookup + `manual_id_overrides`), snapshot to S3. A game that fails to resolve is logged and skipped |
| 3 | `refresh_prices`, `refresh_app_details`, `refresh_reviews`, `refresh_steamcharts_monthly` | run in parallel. Each wraps the existing script unchanged and logs per game to `ingestion_log` |
| 4 | `check_hourly_freshness` | newest file under `raw/steam/player_counts/` must be ≤ **3 h** old (`FRESHNESS_MAX_AGE_HOURS`). The hourly schedule means that tolerates two missed runs |
| 5 | `dbt_build` | runs **only if tasks 2–4 all succeeded**; otherwise it's skipped and the flow run fails |
| 6 | run summary | counts per task and the dbt `PASS/WARN/ERROR` line, in the Prefect log |

These stay outside the flow:
- hourly player counts (separate managed deployment)
- the 5-minute backfill (`src/ingestion/backfill_player_counts.py`, run by hand)
- OpenCritic (manual-only)
- the review histogram

### Retries

- **Per-game tasks** (prices, app details, reviews, SteamCharts) retry **only the games that failed**, once, after **5 minutes**, which is Steam's rate window.
  - Every script's `main` returns `failed_ids` so the task can do this.
  - The task fails if any game still fails.
  - A SteamCharts bot-protection stop is never retried.
- **`resolve_ids`** has no per-game failures, only crashes, so it keeps a normal Prefect retry (1×, 2 min).
- Reruns are safe: raw S3 is append-only and staging keeps the latest fetch per natural key.

### The gate is deliberately strict

**Any** failed ingestion task (or a stale hourly feed) blocks `dbt build`. The marts then keep yesterday's consistent state rather than mixing fresh and failed sources. The cost: one flaky game blocks the whole refresh until it's fixed or retried.

## Run 1: failed, and the gate worked (17:00–17:12 local)

| Task | Result |
|---|---|
| resolve_ids | 54 matched |
| prices | 54 ok, 55,143 records |
| app_details | 54 ok |
| steamcharts_monthly | 54 ok |
| freshness | newest hourly file 0.94 h old |
| **reviews** | **failed: 34 of 54 got HTTP 429 (Too Many Requests); the retry had 33 of 54 still failing** |
| **dbt_build** | **SKIPPED: upstream failed (reviews)**. Flow run state `Failed` |

- **Cause:** `steam_reviews.py` paused only 0.5 s between pages, about 43 requests a minute. Steam's store API allows about 200 requests per 5 minutes, so the script was cut off after roughly 20 games (~200 requests).
- **Wasted retry:** the retry at that time was a whole-task Prefect retry. It reran all 54 games, so the 20 that had already succeeded used up the request budget again.
- **Fixes, both after this run:**
  - `steam_reviews.py` backs off on 429: it honours `Retry-After` (else waits 60 s) and retries the page up to 5 times. The page pause went from 0.5 s to 1.5 s.
  - Task retries now cover only the failed games, after 5 minutes.

The raw files this run wrote are harmless, because staging keeps the latest fetch per natural key. The marts weren't rebuilt.

## Run 2: ingestion fixed; dbt build ran out of memory (17:31–17:56)

| Task | Result |
|---|---|
| resolve_ids | 54 matched |
| prices | 54 ok, 55,143 records, 0 retries |
| app_details | 54 ok, 0 retries |
| **reviews** | **54 ok, 0 retries, no 429s** (1.5 s page pause, ~22 min) |
| steamcharts_monthly | 54 ok, 0 retries |
| freshness | 0.51 h |
| **dbt_build** | **failed: `PASS=54 ERROR=4 SKIP=105`, all four `Out of Memory Error: Allocation failure`** |

- **Where it failed:** the errors hit the models that read S3 JSON (`stg_steam__app_details` and the `stg_opencritic__reviews` tests).
- **Cause:** memory on this machine.
  - It has **5.8 GB of RAM with about 0.8 GB free** at rest (editors and background apps).
  - Today's runs also roughly tripled the raw JSON that staging reads (app details, prices and review files).
  - With 4 dbt threads, parallel DuckDB queries ran out of memory. A standalone `dbt build` failed the same way, so the flow isn't the cause.
- **Partial fix:** a standalone `dbt build --threads 1` passes (`PASS=157`, 1 min 44 s). The flow now passes `--threads $DBT_THREADS` (default 1) to dbt. `~/.dbt/profiles.yml` is unchanged.
- **Still open:** in the Hades runs (Step 5), the in-flow `dbt build` **still ran out of memory with 1 thread**, on `stg_steam__app_details`. The same build passed standalone at 18:07.

### Memory investigation (19:00–19:15). Still open

Everything below was tried on 2026-09-28 in this order.

1. **Option 1 applied to `~/.dbt/profiles.yml`**, as `memory_limit` plus `temp_directory`. It failed twice over:
   - **`temp_directory` breaks dbt-duckdb.** It re-applies the profile settings for every model and test. After the first error, DuckDB refuses with *"Cannot switch temporary directory after the current one has been used"*, and every later model and test failed with that error, until the process exited with code 2. DuckDB already spills to `game_market.duckdb.tmp` by default, so the setting isn't needed.
   - **`memory_limit = 1GB` is too small for `game_coverage`**, which scans the deduplicated 6M-row player-count view: *"failed to allocate data of size 32.0 MiB (741.7 MiB/953.6 MiB used)"*. The intermittent "Allocation failure" on the app-details JSON happened with the cap as well.
   - **So the profile was restored to its original state** (backup taken first), and nothing about memory is changed in it now.
2. **Prefect Cloud is already used** (see "What it is"). No local server competes for memory. The earlier explanation was wrong.
3. **Isolating the failing query.** Outside dbt, the exact compiled `stg_steam__app_details` SQL succeeds in about 3 s, with and without the cap, against the real database file. The rolled-back `CREATE VIEW` succeeds too. All app-details raw files together are **5 MB**, and the Windows commit limit has 5.4 GB free. So neither data volume nor the commit limit explains it.
4. **Inside dbt, it now fails consistently,** standalone too and without the cap. The same standalone build passed at 18:07; the Hades flow runs since then added only a few app-details files.
   - Unexplained. The remaining suspects are memory fragmentation or peak usage within the dbt process (each DuckDB query uses 8 threads) with only about 0.8 GB of RAM free.
   - **Next step:** set DuckDB `threads` (for example 2) in the profile settings, and/or free RAM on this machine. The MySQL and SQL Server services and the IDEs hold several GB.

**State for the demo:** the marts come from the last successful build (18:07). All 55 games are present, including Hades. The failed builds rolled back only their own nodes; the row counts were checked afterwards. Ash's snapshot `data/game_market_demo_2026-09-28.duckdb` exists.

### Permanent fix (after the demo)

Staging re-parses **every raw file ever written** only to keep the latest per key. That cost grows with every run.

- **Keep a current copy per game.** Ingestion additionally writes a *current* copy per game, overwritten each run, for app details, the reviews summary and SteamCharts monthly. For example `raw/steam/app_details/current/app_details_{app_id}.json`. The dated files stay as the append-only history.
- **Staging reads only `current/`,** so the scan size is constant: one small file per game.
- **Prices:** before doing the same, check whether a newer ITAD fetch can contain fewer events than an older one.
  - Checked on 2026-09-28: all 54 games have at least 2 fetches (2026-09-20 → 2026-09-28), and **0 events from older fetches are missing from the newest**. Record counts only grow (e.g. 1364780: 1,927 → 1,959).
  - So a latest-only read loses nothing on current evidence. That's 8 days of evidence, not a guarantee.
  - Keep a guard: fail the run if the newest record count is below the previous one.
- **Reviews** are different: `fact_reviews` deliberately accumulates every review ever fetched. They stay on the dated files, or move to incremental fetching (below).

**Status:** the flow's orchestration works. Ingestion, the gate, the summary and retries all behave as designed, and runs appear in Prefect Cloud. `dbt build` isn't reliable on this machine at the moment, inside or outside the flow.

## Technical debt / future work

- **Where it can run.** dbt builds a local DuckDB file, so the daily flow must run on the machine that holds `data/game_market.duckdb` (a local run or `--serve`). It can't use the managed work pool the hourly flow uses.
- **Local scheduling.** `--serve` schedules only while that process runs. It isn't a deployment in Prefect Cloud.
- **Incremental review fetching.** Reviews are newest-first now (`filter=recent`), so paging could stop at the first review ID already seen. That saves most requests on a daily run. Not implemented.
- **Strict gate.** A per-game failure threshold (for example "≤ 2 games failed") would let one flaky game through without blocking dbt. Not implemented: the strict gate is a deliberate choice.
