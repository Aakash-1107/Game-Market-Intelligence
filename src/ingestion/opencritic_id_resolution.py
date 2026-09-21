# src/ingestion/opencritic_id_resolution.py

import os
import re
import time
import requests
import psycopg2
import duckdb
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL       = os.environ["DATABASE_URL"]
OPENCRITIC_API_KEY = os.environ["OPENCRITIC_API_KEY"]
DUCKDB_PATH        = r"C:\Users\isabe\Desktop\Weiterbildung\Capstone Project\data\game_market.duckdb"

SEARCH_URL         = "https://opencritic-api.p.rapidapi.com/game/search"
RAPIDAPI_HOST      = "opencritic-api.p.rapidapi.com"
SLEEP_SECONDS      = 1.0    # stays under 4 req/sec RapidAPI limit
DAILY_SEARCH_LIMIT = 25     # RapidAPI Basic plan: 25 searches/day hard limit

STOPWORDS = {"the", "edition", "game", "of", "year", "goty", "definitive"}


def normalize(name: str) -> set:
    """Lowercase, strip punctuation, return set of significant tokens."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return {t for t in cleaned.split() if t not in STOPWORDS}


def get_unresolved_games(pg_conn) -> list[tuple[int, str]]:
    """
    Returns games that have a Steam mapping in Neon
    but no OpenCritic mapping yet.
    Names come from DuckDB dim_game.
    Already-resolved filtering done against Neon game_source_mapping.
    """
    # Step 1 — get already-resolved steam_app_ids from Neon
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT steam_app_id FROM game_source_mapping WHERE source = 'OpenCritic'
        """)
        already_resolved = {row[0] for row in cur.fetchall()}

    # Step 2 — get all games + names from DuckDB
    duck = duckdb.connect(DUCKDB_PATH, read_only=True)
    try:
        rows = duck.execute("""
            SELECT steam_app_id, name FROM dim_game ORDER BY steam_app_id
        """).fetchall()
    finally:
        duck.close()

    # Step 3 — filter out already resolved
    return [(app_id, name) for app_id, name in rows if app_id not in already_resolved]


def search_opencritic(game_name: str) -> tuple[list[dict] | None, int | None, str | None]:
    """
    Calls the search endpoint. Returns (results, http_status, error_msg).
    results is None on failure.
    """
    try:
        response = requests.get(
            SEARCH_URL,
            headers={
                "X-RapidAPI-Key": OPENCRITIC_API_KEY,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            params={"criteria": game_name},
            timeout=15,
        )
        response.raise_for_status()
        return response.json(), response.status_code, None
    except requests.HTTPError as e:
        http_code = e.response.status_code if e.response is not None else None
        return None, http_code, f"HTTPError: {e}"
    except Exception as e:
        return None, None, str(e)


def match_candidates(game_name: str, results: list[dict]) -> tuple[str, dict | None, str | None]:
    query_tokens = normalize(game_name)
    candidates = []
    for r in results:
        candidate_tokens = normalize(r["name"])
        if query_tokens <= candidate_tokens:
            candidates.append((r["dist"], len(candidate_tokens), r["id"], r["name"]))

    if not candidates:
        return "no_match", None, None

    candidates.sort(key=lambda x: (x[0], x[1]))  # sort by dist first, then token count
    best = candidates[0]
    rest = candidates[1:]

    # Accept best if it's meaningfully shorter than next candidate (base game vs DLC pattern)
    if rest and (best[1] < rest[0][1]):
        return "matched", {"opencritic_id": best[2], "matched_name": best[3]}, None

    if rest:
        detail = str([(c[2], c[3]) for c in candidates])
        return "ambiguous", None, detail

    return "matched", {"opencritic_id": best[2], "matched_name": best[3]}, None


def write_mapping(conn, steam_app_id: int, opencritic_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO game_source_mapping (steam_app_id, source, source_game_id, mapped_at)
            VALUES (%s, 'OpenCritic', %s, now())
        """, (steam_app_id, str(opencritic_id)))
    conn.commit()


def log_ingestion(conn, steam_app_id: int, status: str,
                   http_status: int | None, error_msg: str | None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log
                (source, stage, game_id, status, http_status, error_message, rows_affected)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            ("opencritic", "id_resolution", str(steam_app_id), status,
             http_status, error_msg, 1 if status == "matched" else 0),
        )
    conn.commit()


def main():
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    print(f"OpenCritic ID resolution started — {run_timestamp}")

    conn = psycopg2.connect(DATABASE_URL)

    games = get_unresolved_games(conn)[:DAILY_SEARCH_LIMIT]
    print(f"{len(games)} unresolved games queued (daily search quota: {DAILY_SEARCH_LIMIT})")

    matched   = []
    ambiguous = []
    no_match  = []
    errored   = []

    for steam_app_id, name in games:
        results, http_status, error_msg = search_opencritic(name)

        if results is None:
            print(f"  ERROR      {steam_app_id:<10} {name:<40} {error_msg}")
            errored.append((steam_app_id, error_msg))
            log_ingestion(conn, steam_app_id, "error", http_status, error_msg)
            time.sleep(SLEEP_SECONDS)
            continue

        status, match, detail = match_candidates(name, results)

        if status == "matched":
            write_mapping(conn, steam_app_id, match["opencritic_id"])
            log_ingestion(conn, steam_app_id, "matched", http_status, None)
            print(f"  MATCHED    {steam_app_id:<10} {name:<40} → {match['opencritic_id']}")
            matched.append(steam_app_id)
        elif status == "ambiguous":
            log_ingestion(conn, steam_app_id, "ambiguous", http_status, detail)
            print(f"  AMBIGUOUS  {steam_app_id:<10} {name:<40} {detail}")
            ambiguous.append(steam_app_id)
        else:
            log_ingestion(conn, steam_app_id, "no_match", http_status, None)
            print(f"  NO MATCH   {steam_app_id:<10} {name:<40}")
            no_match.append(steam_app_id)

        time.sleep(SLEEP_SECONDS)

    print(f"\nResolution run complete")
    print(f"  Matched:   {len(matched)}")
    print(f"  Ambiguous: {len(ambiguous)}  (needs manual review)")
    print(f"  No match:  {len(no_match)}  (needs manual review)")
    print(f"  Errored:   {len(errored)}")

    conn.close()


if __name__ == "__main__":
    main()