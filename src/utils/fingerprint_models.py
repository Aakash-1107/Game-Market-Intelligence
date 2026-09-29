"""Row count + content fingerprint for every relation in the dbt DuckDB file.

Used by the idempotency test (docs/tests/idempotency_test_*.md): run before and after a change,
then diff the two JSON outputs.

    python src/utils/fingerprint_models.py out.json                # fingerprint everything
    python src/utils/fingerprint_models.py out.json --diff base.json  # also compare with a previous run
    python src/utils/fingerprint_models.py out.json --exclude-app-ids 105600 413150  # leave games out

Fingerprint = sum of per-row hashes (order-independent, sensitive to duplicates).
DOUBLE/FLOAT columns are rounded to 6 decimals so parallel-aggregation noise in the last bit
doesn't count as a change. Session TimeZone is UTC so TIMESTAMPTZ text is stable.

Live relations (hourly player counts, current_date spines) are cut at CUTOFF on the listed
column, so data landing after the cutoff doesn't show up as a difference.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("DUCKDB_PATH", str(ROOT / "data" / "game_market.duckdb"))
CUTOFF = "2026-09-28 00:00:00+00"

# relation -> column to cut at CUTOFF
LIVE = {
    "stg_steam__player_counts": "recorded_at",
    "fact_player_activity": "recorded_at",
    "int_player_activity_daily": "activity_date",
    "int_price_daily": "price_date",
    "an_market_anomalies": "activity_date",
    "an_sale_effect": "sale_end",
}


def fingerprint(con, name: str, exclude_ids: list[int]) -> dict:
    cols = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'main' and table_name = ? order by ordinal_position",
        [name],
    ).fetchall()
    exprs = []
    for col, dtype in cols:
        q = f'"{col}"'
        exprs.append(f"round({q}, 6)" if dtype in ("DOUBLE", "FLOAT", "REAL") else q)
    conds = [f"\"{LIVE[name]}\" < '{CUTOFF}'"] if name in LIVE else []
    if exclude_ids and "steam_app_id" in [c for c, _ in cols]:
        conds.append(f"steam_app_id::bigint not in ({', '.join(map(str, exclude_ids))})")
    where = ("where " + " and ".join(conds)) if conds else ""
    n, fp = con.execute(
        f"select count(*), coalesce(sum(hash({', '.join(exprs)})::hugeint), 0)::varchar "
        f'from main."{name}" {where}'
    ).fetchone()
    return {"rows": n, "fingerprint": fp, "cutoff": LIVE.get(name)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--diff")
    ap.add_argument("--only", nargs="*", help="restrict to these relations")
    ap.add_argument("--exclude-app-ids", nargs="*", type=int, default=[],
                    help="leave these games out (relations with a steam_app_id column)")
    args = ap.parse_args()

    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("set TimeZone = 'UTC'")
    con.execute("load httpfs")
    con.execute(f"set s3_region = '{os.environ['AWS_REGION']}'")
    con.execute(f"set s3_access_key_id = '{os.environ['AWS_ACCESS_KEY']}'")
    con.execute(f"set s3_secret_access_key = '{os.environ['AWS_SECRET_KEY']}'")

    names = [r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'main' order by 1"
    ).fetchall()]
    if args.only:
        names = [n for n in names if n in args.only]

    result = {}
    for name in names:
        result[name] = fingerprint(con, name, args.exclude_app_ids)
        r = result[name]
        print(f"{name:<34} {r['rows']:>12,}  {r['fingerprint']}{'  (cut ' + r['cutoff'] + ')' if r['cutoff'] else ''}",
              flush=True)
    Path(args.out).write_text(json.dumps(result, indent=2))

    if args.diff:
        base = json.loads(Path(args.diff).read_text())
        changed = 0
        print("\nDiff vs", args.diff)
        for name in sorted(set(base) | set(result)):
            b, a = base.get(name), result.get(name)
            if b != a:
                changed += 1
                print(f"  {name:<34} {b and b['rows']} -> {a and a['rows']}"
                      f"{'  (content changed)' if b and a and b['rows'] == a['rows'] else ''}")
        print(f"{changed} relation(s) differ" if changed else "identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
