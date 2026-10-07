"""Build the public snapshot of the warehouse for the hosted dashboard (published as a GitHub Release asset).

    python src/utils/build_snapshot.py                 # writes dist/game_market_snapshot.duckdb (overwrites)
    python src/utils/build_snapshot.py --out other.duckdb

Reads the full DuckDB file (src/common/duckdb_path.py) read-only and copies only what the dashboard and the RUNBOOK
example queries need, into the same schema and table names, so the dashboard runs unchanged against either file.
License review (2026-10-07):
  - marts and reporting only, plus observability.mart_ingestion_daily (own pipeline counts) and meta.snapshot_info
  - no raw files, no staging or intermediate; no OpenCritic data (fact_critic_review)
  - fact_reviews without review or reviewer identifiers (only game, vote and playtime at review)
  - fact_player_activity without the 5-minute backfill rows (third-party dataset; the dashboard reads its aggregates
    from fact_player_activity_daily); the self-collected hourly rows stay
  - ITAD price values unchanged
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.common.duckdb_path import duckdb_path  # noqa: E402

DEFAULT_OUT = ROOT / "dist" / "game_market_snapshot.duckdb"
# first hourly reading; stored as 18:29 because readings before 2026-09-20 carry Berlin time labelled as UTC
# (docs/TRD.md, collection incidents)
COLLECTION_START = "2026-09-13 16:29:00+00"
COLLECTION_END = "2026-10-07 14:47:00+00"   # final hourly reading (player_counts_20261007_1447.parquet)

# schema.table -> (select list, where clause)
TABLES = {
    "marts.dim_game": ("*", None),
    "marts.fact_player_activity": ("*", "data_resolution <> '5min'"),
    "marts.fact_player_activity_daily": ("*", None),
    "marts.fact_player_activity_monthly": ("*", None),
    "marts.fact_price_snapshot": ("*", None),
    "marts.fact_price_daily": ("*", None),
    "marts.fact_discount_episode": ("*", None),
    "marts.fact_reviews": ("game_key, steam_app_id, voted_up, playtime_at_review_minutes", None),
    "reporting.rpt_activity_health": ("*", None),
    "reporting.rpt_discount_by_depth": ("*", None),
    "reporting.rpt_discount_effect": ("*", None),
    "reporting.rpt_discount_effect_daily": ("*", None),
    "reporting.rpt_discount_typical": ("*", None),
    "reporting.rpt_game_lifecycle": ("*", None),
    "reporting.rpt_lifecycle_curve": ("*", None),
    "reporting.rpt_lifecycle_typical_curve": ("*", None),
    "reporting.rpt_market_anomalies": ("*", None),
    "observability.mart_ingestion_daily": ("*", None),
}

SOURCES = (
    "Steam: player counts (self-collected hourly), app details and review votes via the Steam Web API and Store API. "
    "Data powered by Steam; not affiliated with Valve. "
    "IsThereAnyDeal (https://isthereanydeal.com): price history, values unchanged. "
    "SteamCharts (https://steamcharts.com): monthly player averages. "
    "Mendeley dataset 'Steam Games Dataset: Player count history, Price history and data about games' "
    "(DOI 10.17632/ycy3sy3vj2.1), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/): included only as "
    "daily aggregates and the results derived from them. "
    "Kaggle 'Steam Monthly Average Players' by Victor Laputsky, CC0: validation source only; it contributed no rows. "
    "Excluded: review text, reviewer and review IDs, raw files, staging and intermediate models, OpenCritic data, "
    "the 5-minute backfill rows."
)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty", "--abbrev=40"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(source: Path, out: Path) -> dict[str, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    for path in (out, out.with_name(out.name + ".wal")):
        path.unlink(missing_ok=True)   # idempotent: always a fresh file

    con = duckdb.connect(str(out))
    con.execute("set TimeZone = 'UTC'")
    con.execute(f"attach '{source.as_posix()}' as src (read_only)")
    counts = {}
    for name, (select, where) in TABLES.items():
        schema, table = name.split(".")
        con.execute(f"create schema if not exists {schema}")
        con.execute(f"create table {name} as select {select} from src.{name}"
                    + (f" where {where}" if where else ""))
        counts[name] = con.execute(f"select count(*) from {name}").fetchone()[0]
    con.execute("detach src")

    con.execute("create schema meta")
    con.execute("""
        create table meta.snapshot_info as select
            ?::timestamptz as snapshot_at,
            ?::timestamptz as collection_start,
            ?::timestamptz as collection_end,
            ?              as git_commit,
            ?              as row_counts_json,
            ?              as sources
    """, [datetime.now(timezone.utc), COLLECTION_START, COLLECTION_END, git_commit(), json.dumps(counts), SOURCES])
    con.execute("checkpoint")
    con.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    source = duckdb_path()
    if not source.exists():
        sys.exit(f"Full database not found: {source}")
    counts = build(source, args.out)
    for name, n in counts.items():
        print(f"{name:<42} {n:>10,}")
    print(f"\n{args.out}: {os.path.getsize(args.out) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
