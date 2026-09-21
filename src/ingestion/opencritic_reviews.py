# src/ingestion/opencritic_reviews.py

import os
import json
import time
import boto3
import requests
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL       = os.environ["DATABASE_URL"]
OPENCRITIC_API_KEY = os.environ["OPENCRITIC_API_KEY"]
AWS_ACCESS_KEY     = os.environ["AWS_ACCESS_KEY"]
AWS_SECRET_KEY     = os.environ["AWS_SECRET_KEY"]
AWS_REGION         = os.environ["AWS_REGION"]
AWS_BUCKET         = os.environ["AWS_BUCKET"]

REVIEW_URL    = "https://opencritic-api.p.rapidapi.com/review/game/{opencritic_id}"
RAPIDAPI_HOST = "opencritic-api.p.rapidapi.com"
SLEEP_SECONDS = 1.0


def get_mapped_games(conn) -> list[tuple[int, str]]:
    """Return (steam_app_id, opencritic_game_id) for all OpenCritic-mapped games."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT steam_app_id, source_game_id
            FROM game_source_mapping
            WHERE source = 'OpenCritic'
            ORDER BY steam_app_id
        """)
        return cur.fetchall()


def fetch_reviews(opencritic_id: str) -> tuple[list | None, int | None, str | None]:
    """
    Fetch all reviews for one OpenCritic game ID.
    Returns (reviews, http_status, error_msg).
    """
    try:
        response = requests.get(
            REVIEW_URL.format(opencritic_id=opencritic_id),
            headers={
                "X-RapidAPI-Key": OPENCRITIC_API_KEY,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json(), response.status_code, None
    except requests.HTTPError as e:
        http_code = e.response.status_code if e.response is not None else None
        return None, http_code, f"HTTPError: {e}"
    except Exception as e:
        return None, None, str(e)


def upload_to_s3(s3_client, steam_app_id: int, opencritic_id: str,
                 reviews: list, run_timestamp: str) -> str:
    """Upload raw review JSON for one game to S3. Returns the S3 key."""
    now = datetime.now(timezone.utc)
    s3_key = (
        f"raw/opencritic/reviews/"
        f"{now.year:04d}/{now.month:02d}/{now.day:02d}/"
        f"reviews_{steam_app_id}_{run_timestamp}.json"
    )

    payload = {
        "ingestion_run":    run_timestamp,
        "fetched_at_utc":   now.isoformat(),
        "source":           "opencritic_reviews",
        "steam_app_id":     steam_app_id,
        "opencritic_id":    opencritic_id,
        "review_count":     len(reviews),
        "reviews":          reviews,
    }

    s3_client.put_object(
        Bucket=AWS_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )

    return s3_key


def log_ingestion(conn, steam_app_id: int, status: str,
                  rows_affected: int, http_status: int | None, error_msg: str | None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log
                (source, stage, game_id, status, http_status, error_message, rows_affected)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            ("opencritic", "reviews", str(steam_app_id), status,
             http_status, error_msg, rows_affected),
        )
    conn.commit()


def main():
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    print(f"OpenCritic review ingestion started — {run_timestamp}")

    conn = psycopg2.connect(DATABASE_URL)
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

    games = get_mapped_games(conn)
    print(f"{len(games)} games mapped to OpenCritic — fetching reviews")

    succeeded = []
    failed    = []

    for steam_app_id, opencritic_id in games:
        reviews, http_status, error_msg = fetch_reviews(opencritic_id)

        if reviews is None:
            print(f"  ERROR  {steam_app_id:<10} OC:{opencritic_id:<8} {error_msg}")
            failed.append((steam_app_id, error_msg))
            log_ingestion(conn, steam_app_id, "error", 0, http_status, error_msg)
            time.sleep(SLEEP_SECONDS)
            continue

        s3_key = upload_to_s3(s3_client, steam_app_id, opencritic_id, reviews, run_timestamp)
        log_ingestion(conn, steam_app_id, "success", len(reviews), http_status, None)
        print(f"  OK     {steam_app_id:<10} OC:{opencritic_id:<8} {len(reviews)} reviews → {s3_key}")
        succeeded.append(steam_app_id)

        time.sleep(SLEEP_SECONDS)

    print(f"\nIngestion complete")
    print(f"  Succeeded: {len(succeeded)}")
    print(f"  Failed:    {len(failed)}")

    conn.close()


if __name__ == "__main__":
    main()