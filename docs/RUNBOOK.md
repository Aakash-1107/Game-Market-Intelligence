# Runbook: using and operating the project

Data collection frozen on 2026-10-07; the published snapshot and the hosted dashboard show the final state.

This guide has two jobs:

- **Part A** starts with the published results (A0), then takes someone from a fresh clone to their own data and
  their own SQL analysis, step by step.
- **Parts B to E** cover running the pipeline: what runs where, how to check it, routine tasks, what to do when an
  external source misbehaves, and how to rebuild.

The steps link to the explanations: flows and health rules in [PIPELINE.md](PIPELINE.md), models and query rules in
[DATA_MODEL.md](DATA_MODEL.md), metric definitions in [ANALYTICS.md](ANALYTICS.md).

---

# Part A. From clone to your own analysis

## A0. Explore the results without credentials

None of this needs an account or a key. What the snapshot contains: [DATA_SOURCES.md](DATA_SOURCES.md).

**Hosted dashboard:** https://game-market-intelligence.streamlit.app

**The dashboard on your machine, from the snapshot:**

```bash
git clone https://github.com/Aakash-1107/Game-Market-Intelligence.git
cd Game-Market-Intelligence
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell; macOS/Linux: source .venv/bin/activate
pip install -r dashboard/requirements.txt

# macOS/Linux
SNAPSHOT_URL=https://github.com/Aakash-1107/Game-Market-Intelligence/releases/download/data-2026-10-07/game_market_snapshot.duckdb streamlit run dashboard/home.py
# Windows PowerShell
$env:SNAPSHOT_URL = "https://github.com/Aakash-1107/Game-Market-Intelligence/releases/download/data-2026-10-07/game_market_snapshot.duckdb"; streamlit run dashboard/home.py
```

Expected: the browser opens the dashboard. The first start downloads the snapshot (about 16 MB) to
`data/game_market_snapshot.duckdb`; later starts open that file without downloading. The Pipeline health page shows
only the frozen collection completeness.

**SQL on the snapshot:**

```bash
curl -L -o game_market_snapshot.duckdb https://github.com/Aakash-1107/Game-Market-Intelligence/releases/download/data-2026-10-07/game_market_snapshot.duckdb
python -c "import duckdb; c = duckdb.connect('game_market_snapshot.duckdb', read_only=True); print(c.sql('select * from meta.snapshot_info'))"
```

In Windows PowerShell, write `curl.exe` instead of `curl`. `duckdb` comes with `dashboard/requirements.txt`. Which
table to use and the rules that keep numbers right: [DATA_MODEL.md, Querying the models](DATA_MODEL.md#querying-the-models).
The example queries in A9 run unchanged on the snapshot.

## A1. What you need

| Need | Why | Cost |
|---|---|---|
| Python 3.11 or newer, Git | Run the code | free |
| An AWS S3 bucket and an IAM user with access to that bucket | All raw data lands here and dbt reads from it | free tier is enough at this scale |
| An IsThereAnyDeal API key (https://isthereanydeal.com/dev/app/) | Price and discount history | free |
| A Postgres database (Neon free tier, or a local Postgres) | Pipeline logs and the Pipeline health page. Optional: without it you still get all analytical models | free |
| Nothing for Steam | The Steam endpoints used here need no key | free |

## A2. Install and configure

```bash
git clone https://github.com/Aakash-1107/Game-Market-Intelligence.git
cd Game-Market-Intelligence
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install dbt-duckdb streamlit prefect
cp .env.example .env                # PowerShell: Copy-Item .env.example .env
```

Fill in `.env`. Required: `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_REGION`, `AWS_BUCKET` (ingestion and dbt) and
`ITAD_API_KEY` (daily flow). Optional: `DATABASE_URL` for the log database; without it, build manually with
`dbt build --target analytics --exclude tag:observability` (B3.2). The settings with defaults are commented out; leave
them so, in particular `DUCKDB_PATH`. Every variable is explained in `.env.example`. Never commit `.env`.

## A3. Create the log tables (skip if you have no log database)

```bash
psql "$DATABASE_URL" -f sql/ddl/ingestion_log.sql
python -m src.observability.run_log --create
```

Expected: no error. The second command prints `tables created`.

## A4. Provide the one-time inputs

Three inputs cannot be fetched on a schedule. Upload them to your bucket **before the first dbt build**, because the
staging models that read them fail while the files are missing.

| Input | Upload to (in your bucket) | Where to get it | Notes |
|---|---|---|---|
| Steam app list | `raw/steam/app_list/steam_app_list.csv` | Steam's app catalogue (`IStoreService/GetAppList`, needs your Steam Web API key) | CSV with a header and two columns, `appid` and `name`. `dim_game` uses it only as a name fallback, so a short CSV listing your own games is enough. No script in this repository creates it |
| Kaggle monthly players | `raw/kaggle/steamcharts_monthly_players/steamcharts.csv` | Kaggle dataset "Steam Monthly Average Players" by Victor Laputsky | Columns used: `month, avg_players, gain, gain_percent, peak_players, name, steam_appid`. Used for months SteamCharts lacks |
| 5-minute backfill | created by the script below | Mendeley dataset "Steam Games Dataset: Player count history, Price history and data about games" (DOI 10.17632/ycy3sy3vj2.1), file `PlayerCountHistoryPart1` | Needed for Q3 and Q4. Set `PLAYER_COUNT_HISTORY_PART1_DIR` in `.env` to the unzipped folder of `{app_id}.csv` files |

Upload with the AWS CLI or the S3 console, for example:

```bash
aws s3 cp steam_app_list.csv s3://$AWS_BUCKET/raw/steam/app_list/steam_app_list.csv
aws s3 cp steamcharts.csv   s3://$AWS_BUCKET/raw/kaggle/steamcharts_monthly_players/steamcharts.csv
```

The backfill runs after you have chosen your games (A5):

```bash
python src/ingestion/backfill_player_counts.py          # all active games found in the dataset
```

Expected: one line per game, `success` for games in the dataset and `no_coverage` for the rest. The staging model
reads every Parquet file under `raw/steam/player_counts/backfill/`, and DuckDB raises an error when a path matches no
files, so **at least one of your games must be in the Mendeley dataset** for the first build to work.

## A5. Choose your games

The project tracks 55 games by default. The list is one file: `game_market/seeds/tracked_games.csv`.

```csv
steam_app_id,game_name,is_active
730,Counter-Strike 2,true
```

Keep the default list, or replace it with your own Steam App IDs (the number in a game's Steam store URL).
`game_name` is only a label. `is_active=false` stops collecting a game but keeps its history. If the ITAD lookup
picks the wrong game, add a row to `game_market/seeds/manual_id_overrides.csv` (source `itad`, status
`matched_manual`, the ITAD ID in `source_game_id`); overrides always win.

## A6. Collect the data

Order matters. Keep the dashboard closed during this step.

```bash
# 1. One hourly player-count reading (also creates the first file the daily flow checks for)
python src/ingestion/steam_player_counts.py

# 2. The daily flow: ITAD IDs, prices, app details, reviews, SteamCharts, freshness check, then dbt build
python flows/daily_market_refresh.py
```

The daily flow needs a hourly file no older than 3 hours (`FRESHNESS_MAX_AGE_HOURS`), so run it right after step 1.
The first full run takes roughly 25 to 30 minutes, mostly Steam reviews, which Steam throttles on purpose.

Expected at the end of the log: every task completed, and `dbt_build` with `PASS=... WARN=0 ERROR=0`.

To keep collecting, run step 1 every hour and the daily flow once a day:

- **Hourly:** schedule `python src/ingestion/steam_player_counts.py` with any scheduler (B3.7).
- **Daily:** `python flows/daily_market_refresh.py --serve` keeps a local scheduler running (07:00 Europe/Berlin), or
  start the command by hand.

## A7. What you have after the first run

Price history, monthly players, game details and reviews are available immediately; 5-minute players after the A4
backfill; hourly players grow from the day you start collecting. Which question needs which data:
[BRD section 7](BRD.md#7-data-requirements).

## A8. Check the result

```bash
cd game_market
dbt test                                           # all tests should pass
dbt show --inline "select count(*) as games from {{ ref('dim_game') }}"
dbt show --inline "select * from {{ ref('game_coverage') }}"    # what each game received (full build only)
```

If something is red, jump to Part C. The dashboard also shows a **Pipeline health** page.

## A9. Query your data

**Where it is.** dbt builds one DuckDB file: `data/game_market.duckdb` in the repository root. It is a local file, not
a server. Which schema and table to use, and the rules that keep numbers right:
[DATA_MODEL.md, Querying the models](DATA_MODEL.md#querying-the-models).

**Connect.** Open the file read-only so you cannot change it by accident:

```python
import duckdb

con = duckdb.connect("data/game_market.duckdb", read_only=True)
df = con.sql("select name, release_date from marts.dim_game order by release_date").df()
print(df.head())
```

The DuckDB command-line tool works as well (`duckdb data/game_market.duckdb -readonly`; install it separately), and
the dashboard's **Game explorer** page is the point-and-click option. DuckDB lets only one process write to the file:
while `dbt build` or the daily flow runs, work on a copy (`copy data\game_market.duckdb data\analysis.duckdb`).

**Example queries.**

```sql
-- 1. Which games are tracked, with genres
select steam_app_id, name, release_date, steam_genres
from marts.dim_game
order by name;

-- 2. Daily players of one game (complete days only)
select activity_date, avg_players, peak_players
from marts.fact_player_activity_daily
where steam_app_id = 1091500 and is_complete_day
order by activity_date;

-- 3. The ten busiest games in the latest month
select g.name, m.avg_players
from marts.fact_player_activity_monthly m
join marts.dim_game g using (steam_app_id)
where m.activity_month = (select max(activity_month) from marts.fact_player_activity_monthly)
order by m.avg_players desc
limit 10;

-- 4. What is discounted right now, deepest first
select g.name, p.price_amount, p.regular_amount, p.discount_pct
from marts.fact_price_daily p
join marts.dim_game g using (steam_app_id)
where p.price_date = (select max(price_date) from marts.fact_price_daily) and p.is_on_sale
order by p.discount_pct desc;

-- 5. Your own question: average players on discounted vs undiscounted days (5-minute window)
--    A raw comparison. It ignores trends and updates; rpt_discount_effect compares each discount with its own
--    14-day baseline instead.
select g.name, p.is_on_sale, round(avg(a.avg_players)) as avg_players, count(*) as days
from marts.fact_price_daily p
join marts.fact_player_activity_daily a
  on a.steam_app_id = p.steam_app_id and a.activity_date = p.price_date
join marts.dim_game g on g.steam_app_id = p.steam_app_id
where a.is_complete_day and a.data_resolution = '5min'
group by g.name, p.is_on_sale
order by g.name, p.is_on_sale;

-- 6. The ready-made Q3 answer: biggest player lifts during valid discounts
select name, sale_start, max_discount_pct, round(lift_during * 100, 1) as lift_during_pct
from reporting.rpt_discount_effect
where episode_status = 'valid'
order by lift_during desc
limit 10;

-- 7. The ready-made Q4 answer: the most unusual single-game days
select a.activity_date, g.name, a.direction, round(a.z_score, 1) as z_score, a.avg_players
from reporting.rpt_market_anomalies a
join marts.dim_game g using (steam_app_id)
where a.is_anomaly and not a.is_market_wide
order by abs(a.z_score) desc
limit 10;

-- 8. Share of positive reviews per game
select g.name, count(*) as reviews, round(avg(r.voted_up::int) * 100, 1) as positive_pct
from marts.fact_reviews r
join marts.dim_game g using (steam_app_id)
group by g.name
order by positive_pct;
```

If a query returns nothing, check the coverage of that game first (`observability.game_coverage`): not every game has
every kind of data.

## A10. Turn a query into a model

When an analysis is worth keeping, make it a dbt model so it is rebuilt, tested and documented with everything else:

1. Create `game_market/models/reporting/rpt_<your_name>.sql`. Read only through `{{ ref('...') }}` and only from
   `marts` models or other `rpt_` models (the layer rules are in [DATA_MODEL.md](DATA_MODEL.md#may-read)).
2. Describe it in `game_market/models/reporting/_reporting__models.yml`: the grain (what one row is), a description,
   and tests on the key.
3. Build it: `dbt build --select rpt_<your_name>` from `game_market/`.
4. If a dashboard page uses it, declare it in `game_market/models/exposures.yml`.

---

# Part B. Operating the pipeline

## B1. What runs where

The hourly script runs wherever you schedule it (B3.7). Everything else runs on your machine: the daily flow (by hand,
or `--serve` for 07:00 Europe/Berlin), the 5-minute backfill, OpenCritic, and the dashboard
(`streamlit run dashboard/home.py`, read-only). Why the daily flow is local: [PIPELINE.md](PIPELINE.md).

## B2. Checking health

| Question | Look here |
|---|---|
| Is everything healthy right now? | Dashboard page **Pipeline health** (needs `DATABASE_URL`) |
| Did the hourly script run? | Your scheduler's history; for the GitHub workflow, the Actions tab, workflow `hourly-steam-player-counts` |
| Which game or request failed? | Table `ingestion_log` (one row per game per stage per run) |
| Which stage of the daily flow failed? | Table `pipeline_run_log` (stages: `resolve_ids`, `ingest_prices`, `ingest_app_details`, `ingest_reviews`, `ingest_steamcharts`, `freshness_check`, `dbt_build`), or the Prefect run summary |
| Which dbt model or test failed? | Table `dbt_node_result`, or `game_market/target/run_results.json` for the last local build |
| What did a game receive, and why is it in or out of Q1 to Q4? | Model `observability.game_coverage` |

From the command line (from `game_market/`):

```bash
dbt show --inline "select * from {{ ref('mart_pipeline_health') }}"
```

Thresholds for ok, warn and fail: [PIPELINE.md](PIPELINE.md#health-rules-observabilitymart_pipeline_health). The daily
sources are expected once a day, so a `warn` on a day you did not start the daily flow is expected.

## B3. Routine tasks

### B3.1 Daily refresh

1. Close the Streamlit dashboard. dbt needs the write lock on the DuckDB file.
2. Run, from the repository root with the virtual environment active:

   ```bash
   python flows/daily_market_refresh.py              # all active games
   python flows/daily_market_refresh.py 1145360      # only these games, for testing one game
   python flows/daily_market_refresh.py --serve      # stay running, scheduled daily 07:00 Europe/Berlin
   ```

3. Read the **Run summary** at the end of the log. Expected: every task completed and `dbt_build` with
   `PASS=... WARN=0 ERROR=0`. If a task failed, `dbt build` was skipped on purpose (gate:
   [PIPELINE.md](PIPELINE.md)); go to C2.
4. Open the dashboard and check **Pipeline health**.

Reruns are safe. Raw S3 is append-only, and staging keeps the latest fetch per natural key.

### B3.2 Build models only

From `game_market/`:

```bash
dbt deps                                                    # first time only (dbt_utils); the daily flow does this itself
dbt build                                                   # full: needs S3 credentials and DATABASE_URL
dbt build --target analytics --exclude tag:observability    # without the log database
dbt build --select +rpt_discount_effect                     # one model and everything it depends on
```

### B3.3 Dashboard

```bash
streamlit run dashboard/home.py
```

It opens `data/game_market.duckdb` read-only. If `DATABASE_URL` is missing or the log database is unreachable, only
the Pipeline health page shows a message; every other page still works.

### B3.4 Add a game

1. Add a row to `game_market/seeds/tracked_games.csv`: `steam_app_id,game_name,is_active` (`true`).
2. If the hourly script runs from GitHub Actions: commit and merge to `main`. The workflow checks out the repository
   on each run, so the game enters hourly collection only after the merge.
3. Run the daily flow for that game: `python flows/daily_market_refresh.py <app_id>`.
4. If the game exists in the Mendeley 5-minute dataset: `python src/ingestion/backfill_player_counts.py <app_id>`.
   It skips games that already have a backfill.
5. Check `observability.game_coverage` for the game. Games without 5-minute data appear in Q1 and Q2 but not in Q3
   and Q4.

### B3.5 Stop collecting a game

Set `is_active` to `false` in `tracked_games.csv`. Ingestion stops, history stays in the models.

### B3.6 OpenCritic (manual only)

Quota: 25 searches and 200 requests per day. Add the OpenCritic ID of a game by hand as a row in
`manual_id_overrides.csv` (source `opencritic`, status `matched_manual`), then run
`python src/ingestion/opencritic_reviews.py`. Only games with such a row are fetched.

### B3.7 Schedule the hourly script

The command is `python src/ingestion/steam_player_counts.py`, once an hour, from the repository root with the
variables of `.env` available.

- **GitHub Actions** (no machine has to stay on): in your copy of the repository, add the repository secrets
  `DATABASE_URL`, `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_REGION`, `AWS_BUCKET`, then add a schedule to
  `.github/workflows/hourly-steam-ingest.yml`:

  ```yaml
  on:
    schedule:
      - cron: "5 * * * *"   # UTC
    workflow_dispatch:
  ```

  The workflow installs `requirements.txt` on each run, so **a package the script imports must be listed there**
  (C1). GitHub may start scheduled runs late or skip them ([TRD section 13.1](TRD.md#131-collection-incidents)).
- **Cron or Windows Task Scheduler** on a machine that stays on: run the command above every hour.

---

# Part C. When something looks off

These are known situations, each one detected and reported by the pipeline. Find the symptom, then the cause and the
fix.

## C1. Hourly health is `warn` or `fail`

1. Check the latest runs in your scheduler (for GitHub Actions: the Actions tab).
2. **Run failed with an import error:** a dependency is missing from `requirements.txt`. Add the package, push to
   `main`, and watch the next run.
3. **Run failed on S3 or the database:** check the credentials (`.env`, or the GitHub Actions secrets). A rotated key
   must be updated there.
4. **No runs at all:** the schedule is missing or disabled (the published workflow has none; B3.7).
5. **Gap in the data:** it cannot be recovered. Steam has no history endpoint for current players.

## C2. Daily flow: a task failed and `dbt_build` was skipped

Read the summary line for the failed task, then find the games in `ingestion_log`:

```sql
select run_timestamp, source, stage, game_id, status, http_status, error_message
from ingestion_log
where status not in ('success', 'matched_auto', 'matched_manual', 'matched_imported', 'no_coverage')
  and run_timestamp > now() - interval '1 day'
order by run_timestamp desc;
```

| Symptom | Cause | Fix |
|---|---|---|
| `reviews`: HTTP 429, or "0 reviews" for several games | Steam throttles review requests (about 200 per 5 minutes) and sometimes answers 200 with an empty page | The script backs off and retries; if games still fail, wait 10 minutes and rerun only those games: `python src/ingestion/steam_reviews.py <app_id> <app_id>`. Never run two review fetches in parallel: Steam's limit is shared |
| `resolve_ids` failed: none of N games resolved | ITAD key invalid or ITAD down | Check `ITAD_API_KEY` and the ITAD status, then rerun. Partial misses only warn |
| `prices` failed for some games | ITAD rate limit or outage | Rerun the daily flow for those games |
| `steamcharts`: stopped by bot protection (exit code 2) | The site served a challenge or robots.txt now disallows `/app` | Do not retry in a loop. Wait, check robots.txt in a browser, rerun later. If it persists, SteamCharts monthly data stays at its last state |
| `freshness_check`: newest hourly file is too old | The hourly script is not running | Fix the hourly script first (C1), then rerun |
| `freshness_check`: no hourly file for today or yesterday | Same, or wrong `AWS_BUCKET` | Check the bucket name and credentials. On a first run, run the hourly script once before the daily flow |

After fixing the cause, rerun the daily flow. It is idempotent.

## C3. dbt build fails

| Symptom | Cause | Fix |
|---|---|---|
| "DuckDB file ... is locked" | The dashboard (or another process) has the file open | Stop Streamlit and rerun |
| Out-of-memory or "Allocation failure" during a build | Too many parallel S3 scans or other memory-heavy programs | Keep `--threads 1` (default), close other heavy programs, or raise `DUCKDB_MEMORY_LIMIT` (default 2GB). Never use a `settings:` entry for `temp_directory`; it must stay in `config_options` |
| Log database error on the full target | `DATABASE_URL` missing or unreachable | Use `--target analytics --exclude tag:observability`. The daily flow falls back to this by itself and warns |
| "No files found that match the pattern" on a first build | One of the one-time inputs or the first hourly or backfill file is missing | Complete A4 and A6 |
| A test fails: uniqueness on a staging model | Two rows share the natural key after deduplication | Inspect the raw files for that source and date and the model's dedup rule (latest fetch per key). Do not delete raw files without a backup |
| A test fails: relationship to `dim_game` | A fact references a game missing from `dim_game`. Often `dim_game` was not rebuilt first, or the game has no Steam appdetails | Run `dbt build --select dim_game+`. If the game never had appdetails, it is out of scope by design |
| `Catalog Error` or missing relation on a fresh DuckDB file | Models not built yet | Run `dbt deps`, then `dbt build` |

Never edit a mart table by hand. Fix the source or the model and rebuild.

## C4. Dashboard shows no or stale data

1. Check when the last `dbt build` succeeded (Pipeline health, `dbt_build` row).
2. If the page shows an error about the DuckDB file, check that the file exists: `data/game_market.duckdb`, or
   `DUCKDB_PATH` if set. dbt, the dashboard and the daily flow resolve `DUCKDB_PATH` the same way (a relative path from
   `game_market/`), so they always use the same file. Without that file the dashboard falls back to the snapshot
   (`SNAPSHOT_URL`, A0).
3. Pipeline health empty: `DATABASE_URL` missing or the database unreachable. This affects only that page.

## C5. Numbers changed after a rebuild

Expected when new data arrived: hourly readings, new discounts, new reviews. To prove that a code change did not
alter existing data, take a fingerprint before and after:

```bash
python src/utils/fingerprint_models.py before.json --schemas staging intermediate marts reporting observability seeds
# make the change, rebuild, then:
python src/utils/fingerprint_models.py after.json --schemas staging intermediate marts reporting observability seeds --diff before.json
```

See the header of `src/utils/fingerprint_models.py` for the cutoff and rename options.

---

# Part D. Rebuild and replay

- **Raw S3 is the source of truth.** It is append-only. Every model can be rebuilt from it with `dbt build`; no
  API needs to be called again.
- **Rebuild everything from raw:** move `data/game_market.duckdb` aside, then `dbt deps` and `dbt build`.
- **Refetch one source for some games:** run the matching script with app IDs (section E2). Staging keeps the latest
  fetch per natural key, so old files do not need deleting.
- **Backups:** the DuckDB file and the S3 bucket are not backed up automatically. Copy `data/game_market.duckdb`
  before risky changes. File names containing `backup` are git-ignored.
- **Cannot be recovered:** hourly player counts for a missed hour (no Steam history endpoint).
- **Reading raw hourly files from before 2026-09-20:** their timestamps are Berlin time
  ([TRD section 13.1](TRD.md#131-collection-incidents)).

---

# Part E. Reference

## E1. Credentials and security

| Secret | Lives in |
|---|---|
| AWS keys, bucket, ITAD key, OpenCritic key, `DATABASE_URL` | Local `.env` (git-ignored) |
| AWS keys, region, bucket and `DATABASE_URL` for the hourly workflow | GitHub Actions repository secrets (names in B3.7) |

To rotate a key: create the new key at the provider, update `.env` and the GitHub Actions secret, run the hourly
workflow once manually, then disable the old key. If a secret was ever committed, rotate it immediately; deleting the
file is not enough because git keeps history. Use an IAM user with access to the one bucket only.

## E2. Command reference

| Task | Command (repository root unless noted) |
|---|---|
| Daily flow, all games | `python flows/daily_market_refresh.py` |
| Daily flow, chosen games | `python flows/daily_market_refresh.py <app_id> ...` |
| Daily flow on a schedule | `python flows/daily_market_refresh.py --serve` |
| One hourly reading | `python src/ingestion/steam_player_counts.py` |
| Resolve ITAD IDs | `python src/ingestion/resolve_ids.py [app_id ...]` |
| Prices | `python src/ingestion/itad_price_history.py [app_id ...]` |
| App details | `python src/ingestion/steam_app_details.py [app_id ...]` |
| Reviews | `python src/ingestion/steam_reviews.py [app_id ...]` |
| SteamCharts monthly | `python src/ingestion/steamcharts_monthly.py [app_id ...]` |
| 5-minute backfill | `python src/ingestion/backfill_player_counts.py [app_id ...]` |
| OpenCritic reviews | `python src/ingestion/opencritic_reviews.py` |
| Create observability tables | `python -m src.observability.run_log --create` |
| dbt full build (from `game_market/`) | `dbt build` |
| dbt without log database | `dbt build --target analytics --exclude tag:observability` |
| dbt docs and lineage | `dbt docs generate` then `dbt docs serve` |
| Find unused models | `dbt parse` then `python ../src/utils/find_unused_nodes.py` |
| Dashboard | `streamlit run dashboard/home.py` |
| Build the public snapshot | `python src/utils/build_snapshot.py` |

## E3. Raw data layout and known limits

Raw layout in S3: [TRD section 4.1](TRD.md#41-raw-layout-in-s3). Known technical limits:
[TRD section 13](TRD.md#13-known-technical-limitations).
