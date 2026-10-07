"""Daily market refresh: ingestion -> checks -> dbt build, as one Prefect flow.

    python flows/daily_market_refresh.py                  # all active games in tracked_games.csv
    python flows/daily_market_refresh.py 1145360          # only these games (testing a new game)
    python flows/daily_market_refresh.py --serve          # keep running, schedule daily at 07:00 Europe/Berlin

Runs on the local machine; no work pool or deployment needed.
Stop the Streamlit dashboard first: dbt needs the write lock on the DuckDB file.

Tasks:
  1. load active games (tracked_games.csv)
  2. resolve ITAD IDs (seed + ITAD lookup + manual_id_overrides; snapshot to S3)
  3. in parallel, each with a retry of failed games and ingestion_log logging:
     ITAD prices, Steam app details, Steam reviews (+ lifetime summary), SteamCharts monthly
  4. freshness check: newest hourly player-count file in S3 is at most FRESHNESS_MAX_AGE_HOURS old
  5. dbt build, only if 2-4 all succeeded; otherwise skipped and the flow run is marked failed. Runs dbt deps
     first when a package from package-lock.yml is missing (fresh clone).
     Target dev (everything) when the log database is reachable, else target analytics without the observability
     models (tag:observability); analytics never depends on Neon.
  6. run summary (counts per task, dbt PASS/WARN/ERROR) in the Prefect log

Observability (src/observability/run_log.py): every stage writes a row to Neon pipeline_run_log (running, then
success / failed / skipped, with counts and the error), and every dbt build (passed or failed) writes one row per
node to dbt_node_result from target/run_results.json. Logging failures only warn; they never fail a task.

A per-game task retries only its failed games, once, 5 minutes later (Steam's rate window); it fails if
any game still fails or the script raises. Reruns are safe: raw S3 is append-only and staging keeps the
latest fetch per natural key. The gate is deliberately strict: any failed ingestion task blocks dbt build.
Not included: the hourly player counts (src/ingestion/steam_player_counts.py, scheduled separately), the 5-minute
backfill (src/ingestion/backfill_player_counts.py, run by hand) and OpenCritic (manual-only).

Technical debt: dbt builds a local DuckDB file, so this flow must run on the machine that holds
data/game_market.duckdb (local run / serve).
"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import duckdb
from dotenv import load_dotenv
from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# the ingestion scripts print "→"/"—"; a Windows console (cp1252) would fail on them
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(ROOT / ".env")

from src.common.duckdb_path import duckdb_path  # noqa: E402
from src.common.tracked_games import load_tracked_app_ids  # noqa: E402
from src.ingestion import itad_price_history, steam_app_details, steam_reviews, steamcharts_monthly  # noqa: E402
from src.ingestion.resolve_ids import resolve_itad_ids  # noqa: E402
from src.observability.run_log import log_skipped, log_stage, record_dbt_results  # noqa: E402

FLOW_NAME = "daily_market_refresh"
# future name in the flow -> stage name in pipeline_run_log
STAGES = {"resolve_ids": "resolve_ids", "prices": "ingest_prices", "app_details": "ingest_app_details",
          "reviews": "ingest_reviews", "steamcharts_monthly": "ingest_steamcharts", "freshness": "freshness_check",
          "dbt_build": "dbt_build"}

DBT_PROJECT_DIR = ROOT / "game_market"
DUCKDB_PATH = duckdb_path()   # the file dbt writes (same resolution as profiles.yml)
# `or`, not a getenv default: an empty value in .env (VAR=) counts as unset
FRESHNESS_MAX_AGE_HOURS = float(os.getenv("FRESHNESS_MAX_AGE_HOURS") or "3")   # hourly schedule: 2 missed runs tolerated
HOURLY_PREFIX = "raw/steam/player_counts/"
# dbt threads for the flow's build (overrides profiles.yml). 1 by default: on a 5.8 GB machine, 4 parallel
# DuckDB queries over the S3 JSON ran out of memory on 2026-09-28; 1 thread builds in ~1.7 min.
DBT_THREADS = os.getenv("DBT_THREADS") or "1"

# resolve_ids: a Prefect retry reruns it (it has no per-game failures, only crashes)
RESOLVE_RETRIES = 1
RESOLVE_RETRY_DELAY_SECONDS = 120
# per-game ingestion tasks: in-task retry of only the failed games, after Steam's 5-minute rate window
GAME_RETRIES = 1
GAME_RETRY_DELAY_SECONDS = 300


class TaskFailed(RuntimeError):
    pass


def current_run_id() -> str:
    return str(flow_run.id or "local")


def run_with_game_retries(name: str, fetch, app_ids: list[int]) -> dict:
    """Run fetch(app_ids) -> counts (with "failed_ids"); retry only the failed games, GAME_RETRIES times,
    GAME_RETRY_DELAY_SECONDS apart. Raises TaskFailed if any game still fails. Returns summed counts."""
    logger = get_run_logger()
    total: dict = {}
    todo = list(app_ids)
    for attempt in range(GAME_RETRIES + 1):
        if attempt:
            logger.warning(f"{name}: retrying {len(todo)} failed game(s) in {GAME_RETRY_DELAY_SECONDS} s: {todo}")
            time.sleep(GAME_RETRY_DELAY_SECONDS)
        counts = fetch(todo)
        for key, value in counts.items():
            if isinstance(value, int) and key != "failed":
                total[key] = total.get(key, 0) + value
        todo = counts["failed_ids"]
        if not todo:
            break
    total["failed_ids"] = todo
    total["retries_used"] = attempt
    if todo:
        raise TaskFailed(f"{name}: {len(todo)} game(s) still failing after {GAME_RETRIES} retry: {todo}")
    return total


@task(name="load_active_games")
def load_active_games(app_ids: list[int] | None) -> list[int]:
    active = load_tracked_app_ids()
    if app_ids:
        inactive = set(app_ids) - set(active)
        if inactive:
            raise ValueError(f"Not active in tracked_games.csv: {sorted(inactive)}")
        return list(app_ids)
    return active


@task(name="resolve_ids", retries=RESOLVE_RETRIES, retry_delay_seconds=RESOLVE_RETRY_DELAY_SECONDS, log_prints=True)
def resolve_ids(app_ids: list[int]) -> dict[int, str]:
    # games that fail to resolve are logged and skipped inside; only a crash fails the task
    with log_stage(current_run_id(), FLOW_NAME, "resolve_ids", records_in=len(app_ids)) as stage:
        mappings = resolve_itad_ids(app_ids)
        stage.records_out = len(mappings)
        # No game resolved at all = ITAD itself is failing (invalid key, outage), not a per-game gap. Without this
        # check, prices would "succeed" on zero games and dbt would build on stale prices (found 2026-09-29).
        if app_ids and not mappings:
            raise TaskFailed(f"resolve_ids: none of {len(app_ids)} game(s) resolved to an ITAD ID "
                             "(check ITAD_API_KEY / ITAD availability)")
        if len(mappings) < len(app_ids):
            get_run_logger().warning(f"resolve_ids: {len(app_ids) - len(mappings)} game(s) not resolved; "
                                     "their prices are not refreshed this run")
    return mappings


@task(name="refresh_prices", log_prints=True)
def refresh_prices(mappings: dict[int, str]) -> dict:
    def fetch(ids: list[int]) -> dict:
        result = itad_price_history.main(mappings={i: mappings[i] for i in ids})
        return {"success": len(result["succeeded"]), "records": result["records"],
                "failed_ids": [app_id for app_id, _ in result["failed"]]}
    with log_stage(current_run_id(), FLOW_NAME, "ingest_prices", records_in=len(mappings)) as stage:
        counts = run_with_game_retries("prices", fetch, list(mappings))
        stage.records_out = counts.get("success")
    return counts


@task(name="refresh_app_details", log_prints=True)
def refresh_app_details(app_ids: list[int]) -> dict:
    with log_stage(current_run_id(), FLOW_NAME, "ingest_app_details", records_in=len(app_ids)) as stage:
        counts = run_with_game_retries("app_details", steam_app_details.main, app_ids)
        stage.records_out = counts.get("success")
    return counts


@task(name="refresh_reviews", log_prints=True)
def refresh_reviews(app_ids: list[int]) -> dict:
    with log_stage(current_run_id(), FLOW_NAME, "ingest_reviews", records_in=len(app_ids)) as stage:
        counts = run_with_game_retries("reviews", steam_reviews.main, app_ids)
        stage.records_out = counts.get("success")
    return counts


@task(name="refresh_steamcharts_monthly", log_prints=True)
def refresh_steamcharts_monthly(app_ids: list[int]) -> dict:
    def fetch(ids: list[int]) -> dict:
        counts = steamcharts_monthly.run(ids)
        if counts["stopped"]:   # bot protection: retrying would only make it worse
            raise TaskFailed(f"steamcharts: stopped by bot protection: {counts['stopped']}")
        return counts
    with log_stage(current_run_id(), FLOW_NAME, "ingest_steamcharts", records_in=len(app_ids)) as stage:
        counts = run_with_game_retries("steamcharts", fetch, app_ids)
        stage.records_out = counts.get("success")
    return counts


@task(name="check_hourly_freshness")
def check_hourly_freshness() -> dict:
    with log_stage(current_run_id(), FLOW_NAME, "freshness_check", records_in=1) as stage:
        result = _check_hourly_freshness()
        stage.records_out = 1
    return result


def _check_hourly_freshness() -> dict:
    s3 = boto3.client(
        "s3",
        region_name=os.environ["AWS_REGION"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["AWS_SECRET_KEY"],
    )
    now = datetime.now(timezone.utc)
    newest = None
    for day in (now, now - timedelta(days=1)):   # hourly files are partitioned by UTC date
        prefix = f"{HOURLY_PREFIX}{day:%Y/%m/%d}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=os.environ["AWS_BUCKET"], Prefix=prefix):
            for obj in page.get("Contents", []):
                if newest is None or obj["LastModified"] > newest["LastModified"]:
                    newest = obj
    if newest is None:
        raise TaskFailed(f"freshness: no hourly player-count file in S3 for today or yesterday ({HOURLY_PREFIX})")
    age_hours = (now - newest["LastModified"]).total_seconds() / 3600
    result = {"newest_file": newest["Key"], "age_hours": round(age_hours, 2), "max_age_hours": FRESHNESS_MAX_AGE_HOURS}
    if age_hours > FRESHNESS_MAX_AGE_HOURS:
        raise TaskFailed(f"freshness: newest hourly file is {age_hours:.1f} h old (max {FRESHNESS_MAX_AGE_HOURS} h): {result}")
    return result


@task(name="dbt_build")
def dbt_build() -> dict:
    with log_stage(current_run_id(), FLOW_NAME, "dbt_build") as stage:
        summary = _dbt_build()
        stage.records_in = sum(summary.values()) or None      # nodes run (pass + warn + error + skip)
        stage.records_out = summary.get("pass", 0) + summary.get("warn", 0)
    return summary


def dbt_mode_args() -> list[str]:
    """Full build (target dev, with the observability models) when the log database is reachable; otherwise the
    analytics-only build (target analytics, no Neon attach, observability models excluded)."""
    url = os.getenv("DATABASE_URL")
    reason = "DATABASE_URL is not set"
    if url:
        try:
            import psycopg2
            psycopg2.connect(url, connect_timeout=10).close()
            return ["--target", "dev"]
        except Exception as e:  # noqa: BLE001
            reason = f"log database unreachable ({type(e).__name__})"
    get_run_logger().warning(f"dbt: {reason}; building target analytics without the observability models")
    return ["--target", "analytics", "--exclude", "tag:observability"]


# DuckDB's error when another process holds the file: Linux/macOS "Could not set lock on file ... Conflicting lock",
# Windows "being used by another process ... File is already open in"
_LOCK_MARKERS = ("could not set lock", "conflicting lock", "used by another process", "already open in")


def _is_lock_error(text: str) -> bool:
    return any(marker in text.lower() for marker in _LOCK_MARKERS)


def _ensure_dbt_packages(dbt: Path) -> None:
    """Run `dbt deps` when a package from package-lock.yml is not installed (dbt_packages/ is gitignored, so a fresh
    clone has none and dbt build would fail on the first dbt_utils macro)."""
    import yaml   # installed with dbt-core
    lock = yaml.safe_load((DBT_PROJECT_DIR / "package-lock.yml").read_text(encoding="utf-8")) or {}
    missing = [p["name"] for p in lock.get("packages", [])
               if not (DBT_PROJECT_DIR / "dbt_packages" / p["name"]).is_dir()]
    if not missing:
        return
    get_run_logger().info(f"dbt: package(s) not installed ({', '.join(missing)}); running dbt deps")
    proc = subprocess.run(
        [str(dbt), "deps", "--no-use-colors", "--profiles-dir", str(DBT_PROJECT_DIR)],
        cwd=DBT_PROJECT_DIR, env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise TaskFailed(f"dbt deps failed (exit {proc.returncode}): {(proc.stdout + proc.stderr)[-2000:]}")


def _dbt_build() -> dict:
    logger = get_run_logger()
    # fail fast with a clear message instead of a dbt stack trace. DuckDB does not create a missing folder, and its
    # IOException covers both a lock and a bad path, so tell them apart.
    if not DUCKDB_PATH.parent.is_dir():
        raise TaskFailed(f"DuckDB folder {DUCKDB_PATH.parent} does not exist: create it or fix DUCKDB_PATH "
                         "(a relative path is resolved from game_market/)")
    try:
        duckdb.connect(str(DUCKDB_PATH)).close()
    except duckdb.IOException as e:
        if _is_lock_error(str(e)):
            raise TaskFailed(
                f"DuckDB file {DUCKDB_PATH} is locked by another process (usually the Streamlit dashboard). "
                f"Stop it and rerun. ({e})"
            ) from e
        raise TaskFailed(f"DuckDB file {DUCKDB_PATH} cannot be opened (check DUCKDB_PATH): {e}") from e

    dbt = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    _ensure_dbt_packages(dbt)
    started = datetime.now(timezone.utc)
    proc = subprocess.run(
        [str(dbt), "build", "--no-use-colors", "--threads", DBT_THREADS, "--profiles-dir", str(DBT_PROJECT_DIR),
         *dbt_mode_args()],
        cwd=DBT_PROJECT_DIR, env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    output = proc.stdout + proc.stderr
    # passed or failed: one row per node in dbt_node_result (skipped if dbt wrote no new run_results.json)
    written = record_dbt_results(current_run_id(), DBT_PROJECT_DIR / "target" / "run_results.json", not_before=started)
    logger.info(f"observability: {written} dbt node result(s) recorded")
    for line in output.splitlines():
        if re.search(r"\b(ERROR|FAIL|WARN)\b", line) and "START" not in line:
            logger.info(line)
    m = re.search(r"Done\. PASS=(\d+) WARN=(\d+) ERROR=(\d+) SKIP=(\d+)", output)
    summary = dict(zip(("pass", "warn", "error", "skip"), map(int, m.groups()))) if m else {}
    if proc.returncode != 0 and "duckdb" in output.lower() and _is_lock_error(output):
        raise TaskFailed("dbt build: DuckDB file is locked (stop the Streamlit dashboard and rerun)")
    if proc.returncode != 0:
        logger.error(output[-3000:])
        raise TaskFailed(f"dbt build failed (exit {proc.returncode}): {summary or 'no summary line'}")
    return summary


@flow(name="daily_market_refresh", log_prints=True)
def daily_market_refresh(app_ids: list[int] | None = None) -> dict:
    logger = get_run_logger()
    games = load_active_games(app_ids)
    logger.info(f"{len(games)} active games")

    mapping_future = resolve_ids.submit(games)
    futures = {
        "resolve_ids": mapping_future,
        "prices": refresh_prices.submit(mapping_future),
        "app_details": refresh_app_details.submit(games),
        "reviews": refresh_reviews.submit(games),
        "steamcharts_monthly": refresh_steamcharts_monthly.submit(games),
        "freshness": check_hourly_freshness.submit(),
    }

    results, failed = {}, []
    run_id = current_run_id()
    for name, fut in futures.items():
        try:
            value = fut.result(raise_on_failure=False)
        except Exception as e:   # a task that never ran (upstream failed) has no result: UnfinishedRun
            value = e
        if fut.state.is_completed():
            results[name] = {"matched": len(value)} if name == "resolve_ids" else value
        else:
            failed.append(name)
            results[name] = f"FAILED: {value}"
            if not fut.state.is_failed():   # never ran (an upstream task failed): the task could not log itself
                upstream = ", ".join(STAGES[n] for n in failed if n != name) or fut.state.name
                log_skipped(run_id, FLOW_NAME, STAGES[name], f"not run: upstream failed ({upstream})")

    if failed:
        results["dbt_build"] = f"SKIPPED: upstream failed ({', '.join(failed)})"
        log_skipped(run_id, FLOW_NAME, "dbt_build", f"upstream failed: {', '.join(STAGES[n] for n in failed)}")
    else:
        dbt_future = dbt_build.submit()
        value = dbt_future.result(raise_on_failure=False)
        if dbt_future.state.is_completed():
            results["dbt_build"] = value
        else:
            failed.append("dbt_build")
            results["dbt_build"] = f"FAILED: {value}"

    logger.info("=== Run summary ===")
    for name, value in results.items():
        logger.info(f"  {name:<20} {value}")

    if failed:
        raise RuntimeError(f"daily_market_refresh failed: {', '.join(failed)}")
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--serve" in args:
        from prefect.schedules import Cron
        daily_market_refresh.serve(
            name="daily-market-refresh-local",
            schedule=Cron("0 7 * * *", timezone="Europe/Berlin"),
        )
    else:
        daily_market_refresh([int(a) for a in args] or None)
