"""Single source of truth for which Steam app IDs this pipeline tracks.

Human-curated input lives in dbt seeds (game_market/seeds/) and is the only thing a person edits:
  - tracked_games.csv:       steam_app_id, game_name (label only), is_active
  - manual_id_overrides.csv: steam_app_id, source, source_game_id, status, note

Add a game by adding one row to tracked_games.csv. Stop a game without losing its history by
setting is_active=false: ingestion skips it, dbt keeps it.
"""
import csv
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parents[2] / "game_market" / "seeds"
SEED_PATH = SEEDS_DIR / "tracked_games.csv"
OVERRIDES_PATH = SEEDS_DIR / "manual_id_overrides.csv"

# override statuses that carry a source_game_id (anything else, i.e. no_coverage, means "skip this source")
MATCHED_OVERRIDE_STATUSES = ("matched_manual", "matched_imported")


def _is_true(value: str | None) -> bool:
    # a missing is_active column/value counts as active
    return (value or "true").strip().lower() in ("true", "1", "yes")


def load_tracked_games(active_only: bool = True) -> dict[int, str]:
    """Return {steam_app_id: game_name} in seed-file order (active rows only by default)."""
    with open(SEED_PATH, newline="", encoding="utf-8") as f:
        return {
            int(row["steam_app_id"]): row["game_name"]
            for row in csv.DictReader(f)
            if not active_only or _is_true(row.get("is_active"))
        }


def load_tracked_app_ids(active_only: bool = True) -> list[int]:
    return list(load_tracked_games(active_only))


def load_manual_overrides(source: str) -> dict[int, dict]:
    """Return {steam_app_id: {"source_game_id", "status", "note"}} for one source ('itad', 'opencritic').

    status is 'matched_manual' (human match) or 'matched_imported' (setup-time match imported from Neon), both
    carrying source_game_id, or 'no_coverage' (source has no entry: skip the game).
    Overrides always win over automatic resolution.
    """
    with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
        return {
            int(row["steam_app_id"]): {
                "source_game_id": row["source_game_id"] or None,
                "status": row["status"],
                "note": row["note"],
            }
            for row in csv.DictReader(f)
            if row["source"].strip().lower() == source
        }
