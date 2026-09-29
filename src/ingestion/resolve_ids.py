"""Resolve source IDs for the active tracked games (ITAD only; OpenCritic is manual-only).

For every active game in game_market/seeds/tracked_games.csv:
  1. a row in manual_id_overrides.csv (source = itad) wins: matched_manual / matched_imported use its ID, no_coverage skips the game;
  2. otherwise the ITAD lookup endpoint resolves the UUID
     (GET https://api.isthereanydeal.com/games/lookup/v1?key=&appid=, see docs.isthereanydeal.com).

Every game is resolved on every run (~55 lookups, well within ITAD's 1,000 requests / 5 minutes), so there is
no cache to go stale and a changed upstream ID is picked up automatically. The full result is written to S3 as
a snapshot (raw/mappings/itad/YYYY/MM/DD/itad_mapping_{ts}.json, read by dbt) and returned in memory for the
price task. Each game gets one ingestion_log row; a game that fails to resolve is logged and skipped, never fatal.

Statuses: matched_auto, matched_manual, matched_imported, no_coverage, not_found, error.

Run from project root:
    python src/ingestion/resolve_ids.py                 # all active games
    python src/ingestion/resolve_ids.py 105600 413150   # only these (must be active)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
import psycopg2
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.tracked_games import (  # noqa: E402
    MATCHED_OVERRIDE_STATUSES, load_manual_overrides, load_tracked_app_ids,
)

load_dotenv()

ITAD_API_KEY   = os.getenv("ITAD_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION     = os.getenv("AWS_REGION")
AWS_BUCKET     = os.getenv("AWS_BUCKET")

LOOKUP_URL    = "https://api.isthereanydeal.com/games/lookup/v1"
SLEEP_SECONDS = 0.3
SOURCE        = "itad"
STAGE         = "resolve_id"

MATCHED = ("matched_auto",) + MATCHED_OVERRIDE_STATUSES


def lookup_itad_id(steam_app_id: int) -> dict | None:
    """Call the ITAD lookup endpoint. Returns the game dict, or None if ITAD has no entry."""
    response = requests.get(
        LOOKUP_URL,
        params={"key": ITAD_API_KEY, "appid": steam_app_id},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data["game"] if data.get("found") else None


def resolve_one(steam_app_id: int, overrides: dict[int, dict]) -> dict:
    override = overrides.get(steam_app_id)
    if override:
        return {
            "steam_app_id":   steam_app_id,
            "itad_game_id":   override["source_game_id"] if override["status"] in MATCHED_OVERRIDE_STATUSES else None,
            "itad_slug":      None,
            "itad_title":     None,
            "status":         override["status"],
            "http_status":    None,
            "error":          None,
        }
    try:
        game = lookup_itad_id(steam_app_id)
        return {
            "steam_app_id": steam_app_id,
            "itad_game_id": game["id"] if game else None,
            "itad_slug":    game.get("slug") if game else None,
            "itad_title":   game.get("title") if game else None,
            "status":       "matched_auto" if game else "not_found",
            "http_status":  200,
            "error":        None,
        }
    except Exception as e:
        http_status = getattr(getattr(e, "response", None), "status_code", None)
        return {
            "steam_app_id": steam_app_id,
            "itad_game_id": None,
            "itad_slug":    None,
            "itad_title":   None,
            "status":       "error",
            "http_status":  http_status,
            "error":        f"{type(e).__name__}: {e}"[:1000],
        }


def write_snapshot(s3_client, results: list[dict], run_at: datetime) -> str:
    s3_key = (
        f"raw/mappings/itad/"
        f"{run_at.year:04d}/{run_at.month:02d}/{run_at.day:02d}/"
        f"itad_mapping_{run_at.strftime('%Y%m%d_%H%M%S')}.json"
    )
    payload = {
        "resolved_at_utc": run_at.isoformat(),
        "source":          SOURCE,
        "game_count":      len(results),
        "mappings":        results,
    }
    s3_client.put_object(
        Bucket=AWS_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    return s3_key


def log_ingestion(conn, result: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log
                (source, stage, game_id, status, http_status, error_message, rows_affected)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (SOURCE, STAGE, str(result["steam_app_id"]), result["status"], result["http_status"],
             result["error"], 1 if result["status"] in MATCHED else 0),
        )
    conn.commit()


def resolve_itad_ids(app_ids: list[int] | None = None) -> dict[int, str]:
    """Resolve ITAD UUIDs, write the snapshot to S3, log each game. Returns {steam_app_id: itad_game_id}
    for matched games only."""
    active = load_tracked_app_ids()
    if app_ids:
        inactive = set(app_ids) - set(active)
        if inactive:
            raise ValueError(f"Not active in tracked_games.csv: {sorted(inactive)}")
    else:
        app_ids = active

    overrides = load_manual_overrides(SOURCE)
    run_at = datetime.now(timezone.utc)
    conn = psycopg2.connect(DATABASE_URL)
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
    )

    results = []
    try:
        for steam_app_id in app_ids:
            result = resolve_one(steam_app_id, overrides)
            results.append(result)
            print(f"  {result['status']:<15} {steam_app_id:<10} {result['itad_game_id'] or result['error'] or ''}")
            try:
                log_ingestion(conn, result)
            except Exception as log_err:
                print(f"  [{steam_app_id}] Failed to write to ingestion_log: {log_err}")
            if steam_app_id not in overrides:
                time.sleep(SLEEP_SECONDS)
    finally:
        conn.close()

    s3_key = write_snapshot(s3_client, results, run_at)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"ITAD ID resolution: {counts} -> s3://{AWS_BUCKET}/{s3_key}")

    return {r["steam_app_id"]: r["itad_game_id"] for r in results if r["status"] in MATCHED}


if __name__ == "__main__":
    resolve_itad_ids([int(a) for a in sys.argv[1:]] or None)
