"""
Fetches Steam's review histogram (positive/negative review counts per period
over a game's lifetime) for tracked games and writes the raw response to S3,
one file per game per run. Logs each game to ingestion_log on Neon.

Endpoint (first-party Steam store endpoint, NOT officially documented):
    https://store.steampowered.com/appreviewhistogram/{app_id}?l=english

The response is stored unmodified. Interpreting the rollup grain
(monthly for established games, finer for young games) is done in staging.

Run from project root:
    python src/ingestion/steam_review_histogram.py
    python src/ingestion/steam_review_histogram.py --app-ids 1091500 105600 3751260
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import boto3
import duckdb
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
DUCKDB_PATH = os.environ["DUCKDB_PATH"]
AWS_ACCESS_KEY = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = os.environ["AWS_SECRET_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_BUCKET = os.environ["AWS_BUCKET"]
DATABASE_URL = os.environ["DATABASE_URL"]

HISTOGRAM_URL = "https://store.steampowered.com/appreviewhistogram/{app_id}"
REQUEST_PARAMS = {"l": "english"}
REQUEST_TIMEOUT_SECONDS = 15
SLEEP_BETWEEN_GAMES = 1.5
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

SOURCE = "steam_review_histogram"
STAGE = "fetch_histogram"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


class HistogramFetchError(Exception):
    """Raised when a histogram cannot be fetched or fails structural checks."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def get_tracked_app_ids(duckdb_path: str) -> list[int]:
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT CAST(steam_app_id AS INTEGER) FROM source_id_mappings"
        ).fetchall()
    finally:
        con.close()
    return sorted(row[0] for row in rows)


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )


def get_pg_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_histogram(app_id: int) -> tuple[dict, int]:
    """
    Fetch the review histogram for one game.
    Retries on network errors, 429 and 5xx. Returns (response JSON, HTTP status).
    Raises HistogramFetchError if the response is unusable.
    """
    url = HISTOGRAM_URL.format(app_id=app_id)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url, params=REQUEST_PARAMS, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise HistogramFetchError(
                    f"request failed after {attempt} attempts: {exc}"
                ) from exc
            wait = 2 ** attempt
            log.warning(f"  [{app_id}] request error ({exc}); retrying in {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code

        if status in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
            wait = 30 * attempt if status == 429 else 2 ** attempt
            log.warning(f"  [{app_id}] HTTP {status}; retrying in {wait}s")
            time.sleep(wait)
            continue

        if status != 200:
            raise HistogramFetchError(f"HTTP {status}", status)

        try:
            data = response.json()
        except ValueError as exc:
            raise HistogramFetchError("response body is not valid JSON", status) from exc

        # Steam signals logical failure in the body, not via HTTP status
        if data.get("success") != 1:
            raise HistogramFetchError(
                f"Steam returned success={data.get('success')!r}", status
            )

        results = data.get("results")
        if not isinstance(results, dict) or not isinstance(results.get("rollups"), list):
            raise HistogramFetchError("response has no results.rollups list", status)

        return data, status

    raise HistogramFetchError("retry loop exited without a result")


def write_to_s3(s3_client, app_id: int, data: dict, http_status: int,
                fetched_at: datetime, bucket: str) -> str:
    timestamp = fetched_at.strftime("%Y%m%d_%H%M")

    payload = {
        "steam_app_id": app_id,
        "fetched_at_utc": fetched_at.isoformat(),
        "request": {
            "url": HISTOGRAM_URL.format(app_id=app_id),
            "params": REQUEST_PARAMS,
        },
        "http_status": http_status,
        "response": data,
    }

    s3_key = (
        f"raw/steam/review_histogram/"
        f"{fetched_at:%Y/%m/%d}/"
        f"review_histogram_{app_id}_{timestamp}.json"
    )

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    return s3_key


def log_to_neon(pg_conn, app_id: int, rows: int, status: str,
                http_status: int | None = None, error: str | None = None):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log
                (run_timestamp, source, stage, game_id, status,
                 http_status, rows_affected, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                datetime.now(timezone.utc),
                SOURCE,
                STAGE,
                str(app_id),
                status,
                http_status,
                rows,
                error,
            ],
        )
    pg_conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Steam review histograms.")
    parser.add_argument(
        "--app-ids",
        type=int,
        nargs="+",
        help="Only fetch these Steam app IDs (default: all tracked games).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log.info("=== Steam Review Histogram Ingestion ===")

    app_ids = args.app_ids or get_tracked_app_ids(DUCKDB_PATH)
    log.info(f"Games to fetch: {len(app_ids)}")

    s3_client = get_s3_client()
    pg_conn = get_pg_connection()

    success_count = 0
    fail_count = 0

    try:
        for app_id in app_ids:
            log.info(f"Fetching histogram for {app_id}...")
            fetched_at = datetime.now(timezone.utc)
            try:
                data, http_status = fetch_histogram(app_id)
                rollups = data["results"]["rollups"]
                if not rollups:
                    log.warning(f"  [{app_id}] histogram has 0 rollups (no reviews?)")
                s3_key = write_to_s3(
                    s3_client, app_id, data, http_status, fetched_at, AWS_BUCKET
                )
                log_to_neon(pg_conn, app_id, len(rollups), "success", http_status)
                log.info(
                    f"  [{app_id}] {len(rollups)} rollups -> s3://{AWS_BUCKET}/{s3_key}"
                )
                success_count += 1
            except Exception as exc:
                http_status = getattr(exc, "http_status", None)
                log.error(f"  [{app_id}] FAILED: {exc}")
                try:
                    log_to_neon(pg_conn, app_id, 0, "error", http_status, str(exc))
                except Exception as log_err:
                    log.error(f"  [{app_id}] Failed to write to ingestion_log: {log_err}")
                fail_count += 1

            time.sleep(SLEEP_BETWEEN_GAMES)
    finally:
        pg_conn.close()

    log.info("=== Done ===")
    log.info(f"  Succeeded : {success_count}")
    log.info(f"  Failed    : {fail_count}")

    # Non-zero exit lets Prefect / the shell detect partial failure
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())