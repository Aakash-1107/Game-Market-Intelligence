"""Single source of truth for which Steam app IDs this pipeline tracks.
Add or remove a game by editing game_market/seeds/tracked_games.csv — nothing else."""
import csv
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[2] / "game_market" / "seeds" / "tracked_games.csv"


def load_tracked_games() -> dict[int, str]:
    """Return {steam_app_id: game_name} in seed-file order."""
    with open(SEED_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {int(row["steam_app_id"]): row["game_name"] for row in reader}


def load_tracked_app_ids() -> list[int]:
    return list(load_tracked_games())
