import os
import time
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()



API_KEY = os.getenv("ITAD_API_KEY")
DB_URL  = os.getenv("DATABASE_URL")

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