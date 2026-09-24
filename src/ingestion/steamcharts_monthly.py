"""SteamCharts monthly player history ingestion.

For every game in game_market/seeds/tracked_games.csv: fetch https://steamcharts.com/app/{app_id}, store the raw
HTML and the extracted monthly table (values kept as text) in S3, and log one row per
game to ingestion_log (Neon). Numeric parsing happens in dbt staging.
"""
import io
import os
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import boto3
import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.tracked_games import load_tracked_app_ids  # noqa: E402

load_dotenv()

SOURCE = "steamcharts"
STAGE = "extract_monthly"
BASE_URL = "https://steamcharts.com/app/{app_id}"
ROBOTS_URL = "https://steamcharts.com/robots.txt"
HEADERS = {"User-Agent": "game-market-capstone/0.1 (student data engineering project)"}
TIMEOUT = 30
SLEEP_SECONDS = 3.0
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 504}
EXPECTED_COLUMNS = ["Month", "Avg. Players", "Gain", "% Gain", "Peak Players"]
OUTPUT_COLUMNS = ["month_label", "avg_players", "gain", "gain_pct", "peak_players"]

DATABASE_URL = os.getenv("DATABASE_URL")
NEON_URL_ENV = "DATABASE_URL"


class BotChallengeError(RuntimeError):
    """Raised when the site serves a bot-protection challenge. The run must stop."""


def check_robots(session: requests.Session) -> None:
    r = session.get(ROBOTS_URL, timeout=TIMEOUT)
    print(f"[robots.txt] status={r.status_code}")
    if r.status_code == 200 and "Disallow: /app" in r.text:
        raise BotChallengeError("robots.txt now disallows /app - stopping.")


def fetch_page(session: requests.Session, app_id: int) -> requests.Response:
    url = BASE_URL.format(app_id=app_id)
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(SLEEP_SECONDS * 2 ** attempt)
            continue
        if r.status_code == 403 or "Just a moment" in r.text:
            raise BotChallengeError(f"Challenge page for app {app_id} (status {r.status_code})")
        if r.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
            time.sleep(SLEEP_SECONDS * 2 ** attempt)
            continue
        return r
    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {last_exc}")


def parse_table(html: str, app_id: int, fetched_at: datetime) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html), keep_default_na=False)
    if len(tables) != 1:
        raise ValueError(f"expected 1 table, found {len(tables)}")
    df = tables[0]
    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(f"unexpected columns: {list(df.columns)}")
    df = df.astype(str)
    df.columns = OUTPUT_COLUMNS
    df.insert(0, "steam_app_id", app_id)
    df["fetched_at_utc"] = fetched_at
    return df


def put_s3(s3, bucket: str, key: str, body: bytes, content_type: str) -> None:
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def log_row(conn, app_id: int, status: str, http_status: int | None,
            rows: int | None, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """insert into ingestion_log
               (source, stage, game_id, status, http_status, error_message, rows_affected)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (SOURCE, STAGE, str(app_id), status, http_status, error, rows),
        )
    conn.commit()


def main() -> int:
    bucket = os.environ["AWS_BUCKET"]
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["AWS_SECRET_KEY"],
        region_name=os.environ["AWS_REGION"],
    )
    conn = psycopg2.connect(os.environ[NEON_URL_ENV])

    run_at = datetime.now(timezone.utc)
    date_path = run_at.strftime("%Y/%m/%d")
    stamp = run_at.strftime("%Y%m%d_%H%M")

    session = requests.Session()
    session.headers.update(HEADERS)

    counts = {"success": 0, "not_found": 0, "failed": 0}
    try:
        check_robots(session)
        app_ids = load_tracked_app_ids()
        print(f"{len(app_ids)} games to fetch")

        for app_id in app_ids:
            try:
                r = fetch_page(session, app_id)
                if r.status_code == 404:
                    log_row(conn, app_id, "not_found", 404, 0)
                    counts["not_found"] += 1
                    print(f"[{app_id}] not on SteamCharts")
                    continue
                r.raise_for_status()

                put_s3(s3, bucket,
                       f"raw/steamcharts/monthly_html/{date_path}/steamcharts_{app_id}_{stamp}.html",
                       r.content, "text/html")

                df = parse_table(r.text, app_id, run_at)
                buf = io.BytesIO()
                df.to_parquet(buf, index=False)
                put_s3(s3, bucket,
                       f"raw/steamcharts/monthly/{date_path}/steamcharts_monthly_{app_id}_{stamp}.parquet",
                       buf.getvalue(), "application/octet-stream")

                log_row(conn, app_id, "success", r.status_code, len(df))
                counts["success"] += 1
                print(f"[{app_id}] {len(df)} rows")
            except BotChallengeError:
                raise
            except Exception as exc:  # per-game failure: log and continue
                log_row(conn, app_id, "failed", getattr(locals().get("r"), "status_code", None),
                        None, f"{type(exc).__name__}: {exc}"[:1000])
                counts["failed"] += 1
                print(f"[{app_id}] FAILED: {exc}")
            finally:
                time.sleep(SLEEP_SECONDS)
    except BotChallengeError as exc:
        print(f"STOPPED: {exc}")
        return 2
    finally:
        conn.close()

    print(f"Done: {counts}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())