"""Where the dbt DuckDB file lives, resolved the same way dbt resolves it (game_market/profiles.yml).

DUCKDB_PATH set and non-empty: that path; a relative path is resolved from game_market/, where dbt runs (so
DUCKDB_PATH=../data/x.duckdb means ROOT/data/x.duckdb for dbt, the dashboard, the daily flow and the fingerprint tool
alike, whatever the working directory). Unset or empty: ROOT/data/game_market.duckdb (profiles.yml's default).

Callers load .env before calling this.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = ROOT / "game_market"
DEFAULT_DUCKDB_PATH = ROOT / "data" / "game_market.duckdb"


def duckdb_path() -> Path:
    value = os.getenv("DUCKDB_PATH")
    if not value:
        return DEFAULT_DUCKDB_PATH
    path = Path(value).expanduser()
    return path if path.is_absolute() else (DBT_PROJECT_DIR / path).resolve()
