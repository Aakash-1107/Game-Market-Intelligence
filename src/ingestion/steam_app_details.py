# src/ingestion/steam_app_details.py

import os
import json
import time
import boto3
import requests
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL   = os.getenv("DATABASE_URL")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION     = os.getenv("AWS_REGION")
AWS_BUCKET     = os.getenv("AWS_BUCKET")

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
SLEEP_SECONDS  = 1.5   # Steam's unofficial rate limit ~200 req/5 min; 1.5s is safe


def get_steam_app_ids(conn) -> list[int]:
    """Return the distinct Steam App IDs tracked in Neon."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT steam_app_id FROM game_source_mapping ORDER BY steam_app_id")
        rows = cur.fetchall()
    return [row[0] for row in rows]


def fetch_app_details(steam_app_id: int) -> dict | None:
    """
    Fetch appdetails for one Steam App ID.
    Returns the inner data dict if success=true, else None.
    The endpoint wraps the response: {"{appid}": {"success": true, "data": {...}}}
    """
    response = requests.get(
        APPDETAILS_URL,
        params={
            "appids": steam_app_id,
            "cc":     "de",   # country code → EUR prices if present
            "l":      "en",   # language → English field values
        },
        timeout=15,
    )
    response.raise_for_status()

    outer = response.json()
    app_key = str(steam_app_id)

    if app_key not in outer:
        return None

    entry = outer[app_key]
    if not entry.get("success"):
        # Steam returns success=false for removed/delisted apps
        return None

    return entry.get("data")


def upload_to_s3(s3_client, steam_app_id: int, data: dict, run_timestamp: str) -> str:
    """Upload raw appdetails JSON for one game to S3. Returns the S3 key."""
    now = datetime.now(timezone.utc)
    s3_key = (
        f"raw/steam/app_details/"
        f"{now.year:04d}/{now.month:02d}/{now.day:02d}/"
        f"app_details_{steam_app_id}_{run_timestamp}.json"
    )

    payload = {
        "ingestion_run":  run_timestamp,
        "fetched_at_utc": now.isoformat(),
        "source":         "steam_appdetails",
        "steam_app_id":   steam_app_id,
        "data":           data,
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
    """Write one row to ingestion_log in Neon."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log
                (source, stage, game_id, status, http_status, error_message, rows_affected)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "steam_appdetails",
                "ingestion",
                str(steam_app_id),
                status,
                http_status,
                error_msg,
                rows_affected,
            ),
        )
    conn.commit()


def main():
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    print(f"Steam appdetails ingestion started — {run_timestamp}")

    conn = psycopg2.connect(DATABASE_URL)
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

    app_ids = get_steam_app_ids(conn)
    print(f"Loaded {len(app_ids)} Steam App IDs from Neon")

    succeeded = []
    failed    = []
    skipped   = []   # success=false from Steam (delisted apps)

    for steam_app_id in app_ids:
        try:
            data = fetch_app_details(steam_app_id)

            if data is None:
                # Steam returned success=false — app delisted or ID invalid
                print(f"  SKIP  {steam_app_id:<10} success=false (delisted or invalid)")
                skipped.append(steam_app_id)
                log_ingestion(conn, steam_app_id, "skipped", 0, 200, "success=false from Steam")
                time.sleep(SLEEP_SECONDS)
                continue

            s3_key = upload_to_s3(s3_client, steam_app_id, data, run_timestamp)
            log_ingestion(conn, steam_app_id, "success", 1, 200, None)

            print(f"  OK    {steam_app_id:<10} {data.get('name', '?'):<40} → {s3_key}")
            succeeded.append(steam_app_id)

        except requests.HTTPError as e:
            http_code = e.response.status_code if e.response is not None else None
            print(f"  HTTP ERROR  {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))
            log_ingestion(conn, steam_app_id, "error", 0, http_code, f"HTTPError: {e}")

        except Exception as e:
            print(f"  ERROR       {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))
            log_ingestion(conn, steam_app_id, "error", 0, None, str(e))

        time.sleep(SLEEP_SECONDS)

    # --- Summary ---
    print(f"\nIngestion complete")
    print(f"  Succeeded: {len(succeeded)}")
    print(f"  Skipped:   {len(skipped)}  (delisted/invalid)")
    print(f"  Failed:    {len(failed)}")

    if failed:
        print(f"\nFailed games:")
        for app_id, err in failed:
            print(f"  {app_id:<10} {err}")

    conn.close()


if __name__ == "__main__":
    main()