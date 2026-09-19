import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import psycopg2
from dotenv import load_dotenv
from prefect import flow

# Load environment variables from .env
load_dotenv(override=True)

URL = "https://api.steampowered.com/IntentionFailureTest/"

# Mapping of games: appid -> game name (55 unique titles)
GAMES = {
    251570: "7 Days to Die",
    1172470: "Apex Legends",
    1086940: "Baldur's Gate 3",
    2807960: "Battlefield 6",
    3419430: "Bongo Cat",
    255710: "Cities: Skylines",
    3321460: "Crimson Desert",
    730: "CS2",
    1091500: "Cyberpunk 2077",
    374320: "Dark Souls III",
    221100: "DayZ",
    588650: "Dead Cells",
    435150: "Divinity: Original Sin 2",
    570: "Dota 2",
    239140: "Dying Light",
    3405690: "EA Sports FC 26",
    1245620: "Elden Ring",
    3932890: "Escape from Tarkov",
    227300: "Euro Truck Simulator 2",
    427520: "Factorio",
    377160: "Fallout 4",
    39210: "Final Fantasy XIV",
    2483190: "Forza Horizon 6",
    3240220: "GTA V",
    394360: "Hearts of Iron IV",
    553850: "Helldivers 2",
    4001890: "How to Fish",
    2767030: "Marvel Rivals",
    2246340: "Monster Hunter Wilds",
    275850: "No Man's Sky",
    2638890: "Onimusha: Way of the Sword",
    2357570: "Overwatch",
    1623730: "Palworld",
    238960: "Path of Exile",
    2694490: "Path of Exile 2",
    218620: "Payday 2",
    578080: "PUBG",
    359550: "Rainbow Six Siege",
    1174180: "Red Dead Redemption 2",
    294100: "RimWorld",
    252490: "Rust",
    489830: "Skyrim SE",
    646570: "Slay the Spire",
    413150: "Stardew Valley",
    281990: "Stellaris",
    1364780: "Street Fighter 6",
    264710: "Subnautica",
    3678970: "TBH: Task Bar Hero",
    105600: "Terraria",
    3751260: "The Blood of Dawnwalker",
    1222670: "The Sims 4",
    292030: "The Witcher 3",
    892970: "Valheim",
    236390: "War Thunder",
    230410: "Warframe",
}

# Resolve paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "player_count.csv")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
DATABASE_URL = os.getenv("DATABASE_URL")


def get_current_player_counts():
    """Fetch live player count for all games in GAMES mapping.

    Returns (records, events): records is the data to persist, and events
    is one entry per game describing the fetch outcome for ingestion_log.
    """
    timestamp = datetime.now(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    records = []
    events = []

    for appid, name in GAMES.items():
        try:
            response = requests.get(URL, params={"appid": appid}, timeout=10)
            response.raise_for_status()
            data = response.json()
            player_count = data.get("response", {}).get("player_count", None)

            records.append({
                "timestamp": timestamp,
                "appid": appid,
                "game_name": name,
                "player_count": player_count,
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


def save_to_postgres(records, db_url):
    """Insert player count records into PostgreSQL (Neon)."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS steam_player_counts (
                    id SERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    appid INTEGER NOT NULL,
                    game_name VARCHAR(100) NOT NULL,
                    player_count INTEGER
                );
            """)

            insert_query = """
                INSERT INTO steam_player_counts (recorded_at, appid, game_name, player_count)
                VALUES (%s, %s, %s, %s);
            """
            for r in records:
                cur.execute(
                    insert_query,
                    (r["timestamp"], r["appid"], r["game_name"], r["player_count"]),
                )

        conn.commit()
        print(f"Successfully inserted {len(records)} records into PostgreSQL.")
    finally:
        conn.close()


def save_to_csv(records):
    """Fallback: append records to local CSV file."""
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "appid", "game_name", "player_count"]
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(records)
    print(f"Appended {len(records)} records to {CSV_FILE}.")


def write_ingestion_log(events, db_url, pipeline_status="success", pipeline_error=None):
    """
    Write per-game ingestion events plus a pipeline-level summary record.
    Always called via finally block — records both success and failure.
    """
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
                    # Normal path — write per-game events
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
                    # Pipeline crashed before any events were collected
                    cur.execute(insert_query, (
                        "steam",
                        "player_count_ingest",
                        None,
                        pipeline_status,
                        None,
                        pipeline_error,
                        0,
                    ))

            conn.commit()
            print(f"Wrote {len(events) or 1} events to ingestion_log.")
        finally:
            conn.close()
    except Exception as e:
        # Log write failed — print so Prefect captures it in run logs
        print(f"CRITICAL: ingestion_log write failed: {e}")


def main():
    print("Starting player count data ingest...")

    pipeline_status = "success"
    pipeline_error = None
    records = []
    events = []

    try:
        records, events = get_current_player_counts()

        if records:
            if DATABASE_URL:
                print("DATABASE_URL found. Writing to PostgreSQL...")
                try:
                    save_to_postgres(records, DATABASE_URL)
                except Exception as e:
                    print(f"PostgreSQL insertion failed: {e}")
                    print("Falling back to local CSV...")
                    save_to_csv(records)
            else:
                print("No DATABASE_URL found in environment. Saving to CSV...")
                save_to_csv(records)
        else:
            print("No records retrieved.")

    except Exception as e:
        pipeline_status = "failed"
        pipeline_error = str(e)
        print(f"Pipeline failed: {e}")
        raise  # re-raise so Prefect marks the run as Failed

    finally:
        # Always runs — success or failure
        if DATABASE_URL:
            print("Writing ingestion log...")
            write_ingestion_log(events, DATABASE_URL, pipeline_status, pipeline_error)
        else:
            print("No DATABASE_URL found; skipping ingestion_log writes.")


@flow
def steam_player_count_ingest():
    main()


if __name__ == "__main__":
    steam_player_count_ingest()