"""
Backfill historical player counts from PlayerCountHistoryPart1 (5-minute resolution)
into S3 as Parquet, matching the existing raw/steam/player_counts/ layout.

Covers 22 of 55 tracked games, Dec 2017 – Aug 2020.

Run from project root:
    python src/ingestion/backfill_player_counts.py

What it does:
  1. Reads each matched CSV from Part1
  2. Filters the known bad row (2017-12-14 01:05, zero)
  3. Converts timestamps to UTC (source is naive — assumed UTC per SteamCharts convention)
  4. Writes one Parquet file per game to S3 under:
       raw/steam/player_counts/backfill/YYYY/MM/DD/{app_id}_backfill.parquet
  5. Logs each game to ingestion_log on Neon
"""

import os
import io
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import boto3
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.tracked_games import load_tracked_app_ids  # noqa: E402

load_dotenv()

# --- Configuration ---
PART1_DIR = Path(r"C:\Users\isabe\Downloads\PLayerCountData\PlayerCountHistoryPart1\PlayerCountHistoryPart1")

AWS_BUCKET = os.environ["AWS_BUCKET"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_ACCESS_KEY = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = os.environ["AWS_SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]

# Known bad row — systematic zero across all Part1 files
BAD_TIMESTAMP = "2017-12-14 01:05"
DATA_RESOLUTION = "5min"

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
    return psycopg2.connect(DATABASE_URL)


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


def main():
    log.info("=== Player Count Backfill — Part1 (5min) ===")

    tracked = set(load_tracked_app_ids())
    s3_client = get_s3_client()
    pg_conn = get_pg_connection()

    matched_files = {
        int(f.stem): f
        for f in PART1_DIR.glob("*.csv")
        if f.stem.isdigit() and int(f.stem) in tracked
    }

    log.info(f"Matched {len(matched_files)} CSVs against tracked games.")

    success_count = 0
    fail_count = 0

    for app_id, filepath in sorted(matched_files.items()):
        log.info(f"Processing {app_id} ({filepath.name})...")
        try:
            df = load_and_clean_csv(filepath, app_id)
            row_count = len(df)
            s3_key = write_to_s3(s3_client, df, app_id, AWS_BUCKET)
            log_to_neon(pg_conn, app_id, s3_key, row_count, "success")
            log.info(f"  [{app_id}] {row_count:,} rows → s3://{AWS_BUCKET}/{s3_key}")
            success_count += 1
        except Exception as e:
            log.error(f"  [{app_id}] FAILED: {e}")
            try:
                log_to_neon(pg_conn, app_id, "", 0, "error", str(e))
            except Exception as log_err:
                log.error(f"  [{app_id}] Failed to write to ingestion_log: {log_err}")
            fail_count += 1

    pg_conn.close()

    log.info("=== Done ===")
    log.info(f"  Succeeded : {success_count}")
    log.info(f"  Failed    : {fail_count}")


if __name__ == "__main__":
    main()