"""
Backfill historical player counts from PlayerCountHistoryPart1 (5-minute resolution, Dec 2017 – Aug 2020)
into S3 as Parquet, matching the existing raw/steam/player_counts/ layout.

Seed-driven and safe to run twice. For every active game in game_market/seeds/tracked_games.csv:
  - backfill Parquet already in S3 (any date folder) -> skip, log 'skipped'
  - game has a CSV in the local dataset             -> clean, write one Parquet file, log 'success'
      cleaning (unchanged since the 2026-09-22 run): drop the systematic zero at 2017-12-14 01:05,
      drop rows with a null timestamp or player count; naive timestamps are treated as UTC
  - game not in the dataset                         -> log 'no_coverage' (normal: ~22 of 55 games are covered)

Not part of any scheduled flow: run it by hand after adding a game.
The dataset is a manual download; its unzipped folder of {app_id}.csv files is PLAYER_COUNT_HISTORY_PART1_DIR in .env.

Run from project root:
    python src/ingestion/backfill_player_counts.py                 # all active games
    python src/ingestion/backfill_player_counts.py 105600 413150   # only these (must be active)

Output key: raw/steam/player_counts/backfill/YYYY/MM/DD/{app_id}_backfill.parquet
"""

import os
import io
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import boto3
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.tracked_games import load_tracked_app_ids  # noqa: E402
from src.common.log_db import connect_log_db  # noqa: E402

load_dotenv()

# --- Configuration ---
PART1_DIR = Path(os.environ["PLAYER_COUNT_HISTORY_PART1_DIR"])   # folder with {app_id}.csv files

AWS_BUCKET = os.environ["AWS_BUCKET"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_ACCESS_KEY = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = os.environ["AWS_SECRET_KEY"]
DATABASE_URL = os.getenv("DATABASE_URL")

# Known bad row — systematic zero across all Part1 files
BAD_TIMESTAMP = "2017-12-14 01:05"
DATA_RESOLUTION = "5min"
BACKFILL_PREFIX = "raw/steam/player_counts/backfill/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )


def get_pg_connection():
    return connect_log_db(DATABASE_URL)


def load_and_clean_csv(filepath: Path, app_id: int) -> pd.DataFrame:
    df = pd.read_csv(filepath)

    # Normalise column names defensively
    df.columns = [c.strip().lower() for c in df.columns]
    # Expected: 'time', 'playercount'

    # Parse timestamp — source has no timezone info
    df["recorded_at"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M", utc=False)

    # Filter known bad row: timestamp AND zero together
    bad_mask = (df["time"] == BAD_TIMESTAMP) & (df["playercount"] == 0)
    bad_count = bad_mask.sum()
    if bad_count > 0:
        log.info(f"  [{app_id}] Filtered {bad_count} known bad row(s) at {BAD_TIMESTAMP}")
        df = df[~bad_mask].copy()

    # Localise to UTC — SteamCharts timestamps are UTC
    df["recorded_at"] = df["recorded_at"].dt.tz_localize("UTC")

    # Add pipeline metadata columns
    df["steam_app_id"] = str(app_id)
    df["data_resolution"] = DATA_RESOLUTION
    df["ingested_at"] = datetime.now(timezone.utc)

    # Keep only what the fact table needs
    df = df[["steam_app_id", "recorded_at", "playercount", "data_resolution", "ingested_at"]]
    df = df.rename(columns={"playercount": "player_count"})

    # Drop any remaining nulls in key columns
    before = len(df)
    df = df.dropna(subset=["recorded_at", "player_count"])
    dropped = before - len(df)
    if dropped > 0:
        log.warning(f"  [{app_id}] Dropped {dropped} rows with null recorded_at or player_count")

    return df


def write_to_s3(s3_client, df: pd.DataFrame, app_id: int, bucket: str) -> str:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)

    today = datetime.now(timezone.utc)
    s3_key = (
        f"raw/steam/player_counts/backfill/"
        f"{today.year}/{today.month:02d}/{today.day:02d}/"
        f"{app_id}_backfill.parquet"
    )

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=buffer.getvalue(),
    )
    return s3_key


def log_to_neon(pg_conn, app_id: int, s3_key: str,
                rows: int, status: str, error: str | None = None):
    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ingestion_log
                (run_timestamp, source, stage, game_id, status, rows_affected, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [
            datetime.now(timezone.utc),
            "steam_backfill",
            "backfill_player_counts",
            str(app_id),
            status,
            rows,
            error,
        ])
    pg_conn.commit()


def existing_backfills(s3_client, bucket: str) -> set[int]:
    """App IDs that already have a backfill Parquet in S3, in any date folder."""
    found = set()
    for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=BACKFILL_PREFIX):
        for obj in page.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1]
            app_id = name.removesuffix("_backfill.parquet")
            if name.endswith("_backfill.parquet") and app_id.isdigit():
                found.add(int(app_id))
    return found


def main(app_ids: list[int] | None = None) -> dict:
    log.info("=== Player Count Backfill — Part1 (5min) ===")

    active = load_tracked_app_ids()
    if app_ids:
        inactive = set(app_ids) - set(active)
        if inactive:
            sys.exit(f"Not active in tracked_games.csv: {sorted(inactive)}")
    else:
        app_ids = active

    # empty value: Path("") is the working directory, which is_dir() would accept
    if not os.environ["PLAYER_COUNT_HISTORY_PART1_DIR"] or not PART1_DIR.is_dir():
        sys.exit(f"PLAYER_COUNT_HISTORY_PART1_DIR is not a folder: {PART1_DIR}")

    s3_client = get_s3_client()
    pg_conn = get_pg_connection()
    already = existing_backfills(s3_client, AWS_BUCKET)

    counts = {"success": 0, "skipped": 0, "no_coverage": 0, "error": 0}
    for app_id in app_ids:
        filepath = PART1_DIR / f"{app_id}.csv"
        try:
            if app_id in already:
                log.info(f"  [{app_id}] skipped: backfill already in S3")
                log_to_neon(pg_conn, app_id, "", 0, "skipped", "backfill already in S3")
                counts["skipped"] += 1
                continue
            if not filepath.is_file():
                log.info(f"  [{app_id}] no_coverage: not in PlayerCountHistoryPart1")
                log_to_neon(pg_conn, app_id, "", 0, "no_coverage", "not in PlayerCountHistoryPart1")
                counts["no_coverage"] += 1
                continue

            log.info(f"Processing {app_id} ({filepath.name})...")
            df = load_and_clean_csv(filepath, app_id)
            row_count = len(df)
            s3_key = write_to_s3(s3_client, df, app_id, AWS_BUCKET)
            log_to_neon(pg_conn, app_id, s3_key, row_count, "success")
            log.info(f"  [{app_id}] {row_count:,} rows → s3://{AWS_BUCKET}/{s3_key}")
            counts["success"] += 1
        except Exception as e:
            log.error(f"  [{app_id}] FAILED: {e}")
            try:
                log_to_neon(pg_conn, app_id, "", 0, "error", str(e))
            except Exception as log_err:
                log.error(f"  [{app_id}] Failed to write to ingestion_log: {log_err}")
            counts["error"] += 1

    pg_conn.close()

    log.info(f"=== Done === {counts}")
    return counts


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or None)