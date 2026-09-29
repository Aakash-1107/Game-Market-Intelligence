"""ITAD price history ingestion for the active tracked games.

The game -> ITAD UUID mapping comes from src/ingestion/resolve_ids.py (seed + ITAD lookup + manual overrides),
passed in memory. The Neon table game_source_mapping is no longer read (obsolete since 2026-09-28).
Each run fetches the full history since SINCE; staging keeps the latest fetch per record.
Logs each game to ingestion_log on Neon.

Run from project root:
    python src/ingestion/itad_price_history.py                 # all active games
    python src/ingestion/itad_price_history.py 105600 413150   # only these (must be active)
"""
import os
import sys
import json
import time
import boto3
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.ingestion.resolve_ids import resolve_itad_ids  # noqa: E402
from src.common.log_db import connect_log_db  # noqa: E402

load_dotenv()

API_KEY        = os.getenv("ITAD_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION     = os.getenv("AWS_REGION")
AWS_BUCKET     = os.getenv("AWS_BUCKET")

HISTORY_URL = "https://api.isthereanydeal.com/games/history/v2"
COUNTRY     = "DE"
SINCE       = "2010-01-01T00:00:00Z"


def fetch_price_history(itad_id: str) -> list:
    """Fetch full price history for one game from ITAD."""
    response = requests.get(
        HISTORY_URL,
        params={
            "key":     API_KEY,
            "id":      itad_id,
            "country": COUNTRY,
            "since":   SINCE,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def upload_to_s3(s3_client, steam_app_id: int, records: list, run_timestamp: str) -> str:
    """Upload raw JSON for one game to S3. Returns the S3 key."""
    now = datetime.now(timezone.utc)
    s3_key = (
        f"raw/itad/price_history/"
        f"{now.year:04d}/{now.month:02d}/{now.day:02d}/"
        f"price_history_{steam_app_id}_{run_timestamp}.json"
    )

    payload = {
        "ingestion_run":  run_timestamp,
        "fetched_at_utc": now.isoformat(),
        "source":         "itad",
        "country":        COUNTRY,
        "since":          SINCE,
        "steam_app_id":   steam_app_id,
        "total_records":  len(records),
        "records":        records,
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
            ("itad", "price_history", str(steam_app_id), status, http_status, error_msg, rows_affected),
        )
    conn.commit()


def main(mappings: dict[int, str] | None = None, app_ids: list[int] | None = None) -> dict:
    """Fetch price history. `mappings` ({steam_app_id: itad_uuid}) comes from resolve_itad_ids;
    if omitted, IDs are resolved first. Returns {"succeeded": [...], "failed": [...], "records": n}."""
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    print(f"ITAD price history ingestion started — {run_timestamp}")

    if mappings is None:
        mappings = resolve_itad_ids(app_ids)

    # --- Connections ---
    conn = connect_log_db(DATABASE_URL)
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

    print(f"{len(mappings)} games with an ITAD ID")

    # --- Fetch history for each game and upload immediately ---
    succeeded     = []
    failed        = []
    total_records = 0

    for steam_app_id, itad_id in mappings.items():
        try:
            records = fetch_price_history(itad_id)

            for record in records:
                record["steam_app_id"] = steam_app_id
                record["itad_game_id"] = itad_id

            s3_key = upload_to_s3(s3_client, steam_app_id, records, run_timestamp)
            total_records += len(records)

            print(f"  OK    {steam_app_id:<10} {len(records):>4} records → {s3_key}")
            succeeded.append(steam_app_id)
            log_ingestion(conn, steam_app_id, "success", len(records), 200, None)

        except requests.HTTPError as e:
            print(f"  HTTP ERROR  {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))
            http_code = e.response.status_code if e.response is not None else None
            log_ingestion(conn, steam_app_id, "error", 0, http_code, f"HTTPError: {e}")

        except Exception as e:
            print(f"  ERROR       {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))
            log_ingestion(conn, steam_app_id, "error", 0, None, str(e))

        time.sleep(0.3)

    # --- Summary ---
    print(f"\nTotal records:   {total_records}")
    print(f"Games succeeded: {len(succeeded)}")
    print(f"Games failed:    {len(failed)}")

    if failed:
        print(f"\nFailed games:")
        for app_id, err in failed:
            print(f"  {app_id:<10} {err}")

    conn.close()

    return {"succeeded": succeeded, "failed": failed, "records": total_records}


if __name__ == "__main__":
    main(app_ids=[int(a) for a in sys.argv[1:]] or None)