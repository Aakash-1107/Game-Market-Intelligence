"""
Fetches Steam reviews for all tracked games and writes raw JSON to S3.
Collects the newest 1,000 reviews per game (10 pages x 100) in English.
filter=recent (sorted by creation time) is required for stable cursor pagination; the default
filter=all sorts by helpfulness, returns a different sample every call and repeats reviews across
pages. Fetches before 2026-09-28 used the default.
Logs each game to ingestion_log on Neon.
Every tracked game is released and has reviews, so an empty first page is Steam throttling (it can answer 200 with
no reviews instead of 429): it is retried like a 429 and, if still empty, logged as a failure, not a skip.

Run from project root:
    python src/ingestion/steam_reviews.py                  # all tracked games
    python src/ingestion/steam_reviews.py 413150 427520    # only these (must be tracked)
"""

import os
import json
import sys
import time
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import boto3
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.tracked_games import load_tracked_app_ids  # noqa: E402
from src.common.log_db import connect_log_db  # noqa: E402

load_dotenv()

# --- Configuration ---
AWS_ACCESS_KEY = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = os.environ["AWS_SECRET_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_BUCKET = os.environ["AWS_BUCKET"]
DATABASE_URL = os.getenv("DATABASE_URL")

MAX_REVIEWS_PER_GAME = 1000
REVIEWS_PER_PAGE = 100
SLEEP_BETWEEN_GAMES = 1.5
# Steam's store endpoints allow roughly 200 requests per 5 minutes; 1.5 s per page stays under it.
SLEEP_BETWEEN_PAGES = 1.5
MAX_429_RETRIES = 5            # per page
DEFAULT_429_WAIT_SECONDS = 60  # when Steam sends no Retry-After header

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


def retry_after_seconds(response: requests.Response) -> float:
    """Seconds to wait after a 429: the Retry-After header (seconds or HTTP date), else the default."""
    value = response.headers.get("Retry-After")
    if value:
        if value.strip().isdigit():
            return float(value)
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            pass
    return DEFAULT_429_WAIT_SECONDS


def get_page(url: str, params: dict, app_id: int) -> requests.Response:
    """GET one review page; on 429 wait (Retry-After, else 60 s) and retry, up to MAX_429_RETRIES times."""
    for attempt in range(MAX_429_RETRIES + 1):
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 429 or attempt == MAX_429_RETRIES:
            break
        wait = retry_after_seconds(response)
        log.warning(f"  [{app_id}] 429 Too Many Requests, waiting {wait:.0f} s "
                    f"(retry {attempt + 1}/{MAX_429_RETRIES})")
        time.sleep(wait)
    response.raise_for_status()
    return response


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
            "filter": "recent",
            "language": "english",
            "review_type": "all",
            "purchase_type": "all",
            "num_per_page": REVIEWS_PER_PAGE,
            "cursor": cursor,
        }

        data = get_page(url, params, app_id).json()
        # an empty first page is a soft rate limit (200 OK, no reviews): wait and retry like a 429
        empty_retries = 0
        while cursor == "*" and (data.get("success") != 1 or not data.get("reviews")):
            if empty_retries == MAX_429_RETRIES:
                raise RuntimeError(f"first page empty after {MAX_429_RETRIES} retries "
                                   f"(success={data.get('success')}); likely Steam rate limiting")
            empty_retries += 1
            log.warning(f"  [{app_id}] first page empty, waiting {DEFAULT_429_WAIT_SECONDS} s "
                        f"(retry {empty_retries}/{MAX_429_RETRIES})")
            time.sleep(DEFAULT_429_WAIT_SECONDS)
            data = get_page(url, params, app_id).json()

        # Capture summary from first page only
        if not query_summary:
            query_summary = data.get("query_summary", {})

        reviews = data.get("reviews", [])

        # Stop if no reviews returned (past the first page: the end of the reviews)
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
        time.sleep(SLEEP_BETWEEN_PAGES)

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


def main(requested: list[int] | None = None) -> dict:
    """Fetch reviews for all active games, or only `requested`. Returns counts per outcome and
    failed_ids, so a caller can retry only the games that failed."""
    log.info("=== Steam Reviews Ingestion ===")

    app_ids = load_tracked_app_ids()
    log.info(f"Tracked games: {len(app_ids)}")

    if requested:
        untracked = set(requested) - set(app_ids)
        if untracked:
            raise ValueError(f"Not active in tracked_games.csv: {sorted(untracked)}")
        app_ids = requested
        log.info(f"Restricted to {len(app_ids)} requested games")

    s3_client = get_s3_client()
    pg_conn = get_pg_connection()

    success_count = 0
    skipped_count = 0
    fail_count = 0
    failed_ids = []

    for app_id in app_ids:
        log.info(f"Fetching reviews for {app_id}...")
        try:
            reviews, query_summary = fetch_reviews_for_game(app_id)
            if not reviews:
                log.warning(f"  [{app_id}] SKIPPED: 0 reviews returned")
                log_to_neon(pg_conn, app_id, 0, "skipped", "0 reviews returned")
                skipped_count += 1
                time.sleep(SLEEP_BETWEEN_GAMES)
                continue
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
            failed_ids.append(app_id)

        time.sleep(SLEEP_BETWEEN_GAMES)

    pg_conn.close()
    log.info("=== Done ===")
    log.info(f"  Succeeded : {success_count}")
    log.info(f"  Skipped   : {skipped_count}  (0 reviews)")
    log.info(f"  Failed    : {fail_count}")

    return {"success": success_count, "skipped": skipped_count, "failed": fail_count, "failed_ids": failed_ids}


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or None)