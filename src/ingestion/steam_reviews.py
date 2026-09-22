"""
Fetches Steam reviews for all tracked games and writes raw JSON to S3.
Collects up to 1,000 reviews per game (10 pages x 100) in English.
Logs each game to ingestion_log on Neon.

Run from project root:
    python src/ingestion/steam_reviews.py
"""

import os
import json
import time
import logging
from datetime import datetime, timezone

import requests
import boto3
import duckdb
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
DUCKDB_PATH = r"C:\Users\isabe\Desktop\Weiterbildung\Capstone Project\data\game_market.duckdb"

AWS_ACCESS_KEY = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = os.environ["AWS_SECRET_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_BUCKET = os.environ["AWS_BUCKET"]
DATABASE_URL = os.environ["DATABASE_URL"]

MAX_REVIEWS_PER_GAME = 1000
REVIEWS_PER_PAGE = 100
SLEEP_BETWEEN_GAMES = 1.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def get_tracked_app_ids(duckdb_path: str) -> list[int]:
    con = duckdb.connect(duckdb_path)
    rows = con.execute(
        "SELECT DISTINCT CAST(steam_app_id AS INTEGER) FROM source_id_mappings"
    ).fetchall()
    con.close()
    return sorted([row[0] for row in rows])


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )


def get_pg_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_reviews_for_game(app_id: int) -> tuple[list[dict], dict]:
    """
    Fetch up to MAX_REVIEWS_PER_GAME reviews for one game.
    Returns (reviews list, query_summary dict).
    """
    url = f"https://store.steampowered.com/appreviews/{app_id}"
    cursor = "*"
    all_reviews = []
    query_summary = {}

    while len(all_reviews) < MAX_REVIEWS_PER_GAME:
        params = {
            "json": 1,
            "language": "english",
            "review_type": "all",
            "purchase_type": "all",
            "num_per_page": REVIEWS_PER_PAGE,
            "cursor": cursor,
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Capture summary from first page only
        if not query_summary:
            query_summary = data.get("query_summary", {})

        reviews = data.get("reviews", [])

        # Stop if no reviews returned
        if not reviews:
            break

        # Extract only the fields we need
        for r in reviews:
            all_reviews.append({
                "recommendationid": r.get("recommendationid"),
                "timestamp_created": r.get("timestamp_created"),
                "timestamp_updated": r.get("timestamp_updated"),
                "voted_up": r.get("voted_up"),
                "votes_up": r.get("votes_up"),
                "weighted_vote_score": r.get("weighted_vote_score"),
                "steam_purchase": r.get("steam_purchase"),
                "received_for_free": r.get("received_for_free"),
                "written_during_early_access": r.get("written_during_early_access"),
                "playtime_at_review": r.get("author", {}).get("playtime_at_review"),
                "playtime_forever": r.get("author", {}).get("playtime_forever"),
            })

        new_cursor = data.get("cursor")

        # Stop if cursor didn't change (no more pages)
        if new_cursor == cursor:
            break

        cursor = new_cursor

        # Small delay between pages to be polite
        time.sleep(0.5)

    return all_reviews[:MAX_REVIEWS_PER_GAME], query_summary


def write_to_s3(s3_client, app_id: int, reviews: list[dict],
                query_summary: dict, bucket: str) -> str:
    today = datetime.now(timezone.utc)
    timestamp = today.strftime("%Y%m%d_%H%M")

    payload = {
        "steam_app_id": app_id,
        "fetched_at": today.isoformat(),
        "query_summary": query_summary,
        "reviews": reviews,
    }

    s3_key = (
        f"raw/steam/reviews/"
        f"{today.year}/{today.month:02d}/{today.day:02d}/"
        f"reviews_{app_id}_{timestamp}.json"
    )

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    return s3_key


def log_to_neon(pg_conn, app_id: int, rows: int,
                status: str, error: str | None = None):
    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ingestion_log
                (run_timestamp, source, stage, game_id, status, rows_affected, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [
            datetime.now(timezone.utc),
            "steam_reviews",
            "fetch_reviews",
            str(app_id),
            status,
            rows,
            error,
        ])
    pg_conn.commit()


def main():
    log.info("=== Steam Reviews Ingestion ===")

    app_ids = get_tracked_app_ids(DUCKDB_PATH)
    log.info(f"Tracked games: {len(app_ids)}")

    s3_client = get_s3_client()
    pg_conn = get_pg_connection()

    success_count = 0
    fail_count = 0

    for app_id in app_ids:
        log.info(f"Fetching reviews for {app_id}...")
        try:
            reviews, query_summary = fetch_reviews_for_game(app_id)
            s3_key = write_to_s3(s3_client, app_id, reviews, query_summary, AWS_BUCKET)
            log_to_neon(pg_conn, app_id, len(reviews), "success")
            log.info(f"  [{app_id}] {len(reviews)} reviews → s3://{AWS_BUCKET}/{s3_key}")
            success_count += 1
        except Exception as e:
            log.error(f"  [{app_id}] FAILED: {e}")
            try:
                log_to_neon(pg_conn, app_id, 0, "error", str(e))
            except Exception as log_err:
                log.error(f"  [{app_id}] Failed to write to ingestion_log: {log_err}")
            fail_count += 1

        time.sleep(SLEEP_BETWEEN_GAMES)

    pg_conn.close()
    log.info("=== Done ===")
    log.info(f"  Succeeded : {success_count}")
    log.info(f"  Failed    : {fail_count}")


if __name__ == "__main__":
    main()