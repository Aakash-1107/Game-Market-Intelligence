import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"

# Mapping of games: appid -> game name
GAMES = {
    251570: "7 Days to Die",
    1172470: "Apex Legends",
    1086940: "Baldur's Gate 3",
    2807960: "Battlefield 6",
    3419430: "Bongo Cat",
    3321460: "Crimson Desert",
    730: "CS2",
    1091500: "Cyberpunk 2077",
    221100: "DayZ",
    570: "Dota 2",
    3405690: "EA Sports FC 26",
    1245620: "Elden Ring",
    3932890: "Escape from Tarkov",
    227300: "Euro Truck Simulator 2",
    427520: "Factorio",
    39210: "Final Fantasy XIV",
    2483190: "Forza Horizon 6",
    3240220: "GTA V",
    553850: "Helldivers 2",
    4001890: "How to Fish",
    2767030: "Marvel Rivals",
    2246340: "Monster Hunter Wilds",
    275850: "No Man's Sky",
    2638890: "Onimusha: Way of the Sword",
    2357570: "Overwatch",
    1623730: "Palworld",
    2694490: "Path of Exile 2",
    218620: "Payday 2",
    578080: "PUBG",
    359550: "Rainbow Six Siege",
    1174180: "Red Dead Redemption 2",
    252490: "Rust",
    489830: "Skyrim",
    413150: "Stardew Valley",
    1364780: "Street Fighter 6",
    3678970: "TBH: Task Bar Hero",
    105600: "Terraria",
    3751260: "The Blood of Dawnwalker",
    1222670: "The Sims 4",
    892970: "Valheim",
    230410: "Warframe",
}

# Resolve paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "player_count.csv")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
DATABASE_URL = os.getenv("DATABASE_URL")


def get_current_player_counts():
    """Fetch live player count for all games in GAMES mapping."""
    timestamp = datetime.now(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    records = []

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
            print(f"[{timestamp}] {name} ({appid}): {player_count} players")
        except Exception as e:
            print(f"Error fetching appid {appid} ({name}): {e}")

    return records


def save_to_postgres(records, db_url):
    """Insert player count records into PostgreSQL (Neon)."""
    import psycopg2

    # Connect to PostgreSQL
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # Create table if it doesn't exist yet
            cur.execute("""
                CREATE TABLE IF NOT EXISTS steam_player_counts (
                    id SERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    appid INTEGER NOT NULL,
                    game_name VARCHAR(100) NOT NULL,
                    player_count INTEGER
                );
            """)

            # Insert batch
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


def main():
    print("Starting player count data ingest...")
    records = get_current_player_counts()

    if not records:
        print("No records retrieved. Exiting.")
        return

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


if __name__ == "__main__":
    main()
