import os
import json
import time
import boto3
import requests
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

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


def get_itad_mappings(conn) -> dict[int, str]:
    """Read all ITAD mappings from Neon. Returns {steam_app_id: itad_uuid}."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT steam_app_id, source_game_id FROM game_source_mapping WHERE source = 'itad'"
        )
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


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


def main():
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    print(f"ITAD price history ingestion started — {run_timestamp}")

    # --- Connections ---
    conn = psycopg2.connect(DATABASE_URL)
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

    # --- Load mappings ---
    mappings = get_itad_mappings(conn)
    print(f"Loaded {len(mappings)} ITAD mappings from Neon")

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

        except requests.HTTPError as e:
            print(f"  HTTP ERROR  {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))

        except Exception as e:
            print(f"  ERROR       {steam_app_id:<10} {e}")
            failed.append((steam_app_id, str(e)))

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


if __name__ == "__main__":
    main()