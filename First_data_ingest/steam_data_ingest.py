import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv
from prefect import flow

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.tracked_games import load_tracked_games  # noqa: E402

load_dotenv(override=True)

URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"

GAMES = load_tracked_games()

DATABASE_URL   = os.getenv("DATABASE_URL")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION     = os.getenv("AWS_REGION", "eu-central-1")
AWS_BUCKET     = os.getenv("AWS_BUCKET", "game-market-raw")


def get_current_player_counts():
    """Fetch live player count for all games. Returns (records, events)."""
    # Use UTC from now onward — previous data was Berlin time (documented in DATA_QUALITY.md)
    timestamp = datetime.now(timezone.utc)
    records = []
    events = []

    for appid, name in GAMES.items():
        try:
            response = requests.get(URL, params={"appid": appid}, timeout=10)
            response.raise_for_status()
            player_count = response.json().get("response", {}).get("player_count", None)

            records.append({
                "appid": appid,
                "game_name": name,
                "player_count": player_count,
                "recorded_at": timestamp,
            })
            events.append({
                "source": "steam",
                "stage": "raw",
                "game_id": str(appid),
                "status": "success",
                "http_status": response.status_code,
                "error_message": None,
                "rows_affected": 1,
            })
            print(f"[{timestamp}] {name} ({appid}): {player_count} players")

        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            events.append({
                "source": "steam",
                "stage": "raw",
                "game_id": str(appid),
                "status": "failed",
                "http_status": status_code,
                "error_message": str(e),
                "rows_affected": 0,
            })
            print(f"Error fetching appid {appid} ({name}): {e}")

    return records, events


def save_to_s3(records):
    """Write player count records as a dated Parquet file to AWS S3."""
    df = pd.DataFrame(records)

    # Partition by UTC date, filename includes hour for uniqueness
    now_utc = datetime.now(timezone.utc)
    partition = now_utc.strftime("%Y/%m/%d")
    filename  = now_utc.strftime("player_counts_%Y%m%d_%H%M.parquet")
    s3_key    = f"raw/steam/player_counts/{partition}/{filename}"

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)

    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    s3.put_object(Bucket=AWS_BUCKET, Key=s3_key, Body=buffer.getvalue())
    print(f"Uploaded {len(records)} records to s3://{AWS_BUCKET}/{s3_key}")


def write_ingestion_log(events, db_url, pipeline_status="success", pipeline_error=None):
    """Write per-game ingestion events to Neon ingestion_log."""
    try:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ingestion_log (
                        run_id          UUID DEFAULT gen_random_uuid(),
                        run_timestamp   TIMESTAMPTZ DEFAULT NOW(),
                        source          VARCHAR,
                        stage           VARCHAR,
                        game_id         VARCHAR,
                        status          VARCHAR,
                        http_status     INTEGER,
                        error_message   TEXT,
                        rows_affected   INTEGER
                    );
                """)

                insert_query = """
                    INSERT INTO ingestion_log
                        (source, stage, game_id, status, http_status, error_message, rows_affected)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """

                if events:
                    for event in events:
                        cur.execute(insert_query, (
                            event["source"],
                            event["stage"],
                            event["game_id"],
                            event["status"],
                            event["http_status"],
                            event["error_message"],
                            event["rows_affected"],
                        ))
                else:
                    cur.execute(insert_query, (
                        "steam", "player_count_ingest", None,
                        pipeline_status, None, pipeline_error, 0,
                    ))

            conn.commit()
            print(f"Wrote {len(events) or 1} events to ingestion_log.")
        finally:
            conn.close()
    except Exception as e:
        print(f"CRITICAL: ingestion_log write failed: {e}")


def main():
    print("Starting player count data ingest...")

    pipeline_status = "success"
    pipeline_error  = None
    records = []
    events  = []

    try:
        records, events = get_current_player_counts()

        if records:
            save_to_s3(records)
        else:
            print("No records retrieved.")

    except Exception as e:
        pipeline_status = "failed"
        pipeline_error  = str(e)
        print(f"Pipeline failed: {e}")
        raise

    finally:
        if DATABASE_URL:
            write_ingestion_log(events, DATABASE_URL, pipeline_status, pipeline_error)
        else:
            print("No DATABASE_URL — skipping ingestion_log.")


@flow
def steam_player_count_ingest():
    main()


if __name__ == "__main__":
    steam_player_count_ingest()