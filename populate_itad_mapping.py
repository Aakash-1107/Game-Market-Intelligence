import os
import time
import requests
import psycopg2
from dotenv import load_dotenv

from src.common.tracked_games import load_tracked_games

load_dotenv()



API_KEY = os.getenv("ITAD_API_KEY")
DB_URL  = os.getenv("DATABASE_URL")

GAMES = load_tracked_games()

LOOKUP_URL = "https://api.isthereanydeal.com/games/lookup/v1"

def lookup_itad_id(steam_app_id: int) -> dict | None:
    """Call ITAD lookup endpoint. Returns game dict or None if not found."""
    response = requests.get(
        LOOKUP_URL,
        params={"key": API_KEY, "appid": steam_app_id},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("found"):
        return None

    return data["game"]


def upsert_mapping(cur, steam_app_id: int, itad_id: str) -> None:
    cur.execute(
        """
        INSERT INTO game_source_mapping (steam_app_id, source, source_game_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (steam_app_id, source) DO UPDATE
            SET source_game_id = EXCLUDED.source_game_id,
                mapped_at      = now()
        """,
        (steam_app_id, "itad", itad_id),
    )


def main():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    found     = []
    not_found = []
    errors    = []

    for steam_app_id, game_name in GAMES.items():
        try:
            game = lookup_itad_id(steam_app_id)

            if game is None:
                print(f"  NOT FOUND  {steam_app_id:<10} {game_name}")
                not_found.append((steam_app_id, game_name))
            else:
                itad_id = game["id"]
                upsert_mapping(cur, steam_app_id, itad_id)
                print(f"  OK         {steam_app_id:<10} {game_name:<35} {itad_id}")
                found.append((steam_app_id, game_name, itad_id))

        except requests.HTTPError as e:
            print(f"  HTTP ERROR {steam_app_id:<10} {game_name} — {e}")
            errors.append((steam_app_id, game_name, str(e)))

        except Exception as e:
            print(f"  ERROR      {steam_app_id:<10} {game_name} — {e}")
            errors.append((steam_app_id, game_name, str(e)))

        time.sleep(0.3)  # 55 games at 0.3s = ~17s total, well within rate limit

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Found and mapped:  {len(found)}")
    print(f"Not found in ITAD: {len(not_found)}")
    print(f"Errors:            {len(errors)}")

    if not_found:
        print(f"\nNot found:")
        for app_id, name in not_found:
            print(f"  {app_id:<10} {name}")

    if errors:
        print(f"\nErrors:")
        for app_id, name, err in errors:
            print(f"  {app_id:<10} {name} — {err}")


if __name__ == "__main__":
    main()