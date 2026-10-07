"""Row count + content fingerprint for every relation in the dbt DuckDB file.

Used by the idempotency test (docs/tests/idempotency_test_*.md): run before and after a change,
then diff the two JSON outputs.

    python src/utils/fingerprint_models.py out.json                # fingerprint everything
    python src/utils/fingerprint_models.py out.json --diff base.json  # also compare with a previous run
    python src/utils/fingerprint_models.py out.json --exclude-app-ids 105600 413150  # leave games out
    python src/utils/fingerprint_models.py out.json --schemas staging intermediate marts reporting observability seeds
        --diff base.json --rename mart_discount_effect=rpt_discount_effect   # after a schema move / model rename
    python src/utils/fingerprint_models.py out.json ... --drop-columns dim_game.new_col   # existing columns only

Default is schema `main` only, so reports from before the 2026-09-29 layer refactor stay comparable.
Keys are bare relation names (unique across the dbt schemas); --rename maps old baseline names to new ones.

Fingerprint = sum of per-row hashes (order-independent, sensitive to duplicates).
DOUBLE/FLOAT columns are rounded to 6 decimals so parallel-aggregation noise in the last bit
doesn't count as a change. Session TimeZone is UTC so TIMESTAMPTZ text is stable.

Live relations (hourly player counts, current_date spines) are cut at CUTOFF on the listed
column, so data landing after the cutoff doesn't show up as a difference. DATE columns are cut at the
cutoff's UTC date (complete days only), so a day still collecting hourly readings is left out.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.common.duckdb_path import duckdb_path  # noqa: E402

DB_PATH = str(duckdb_path())   # the file dbt writes (same resolution as profiles.yml)
CUTOFF = "2026-09-28 00:00:00+00"

# relation -> column to cut at CUTOFF
LIVE = {
    "stg_steam__player_counts": "recorded_at",
    "fact_player_activity": "recorded_at",
    "int_player_activity_daily": "activity_date",
    "int_price_daily": "price_date",
    "an_market_anomalies": "activity_date",
    "an_sale_effect": "sale_end",
    "rpt_market_anomalies": "activity_date",
    "rpt_discount_effect": "sale_end",
    "fact_player_activity_daily": "activity_date",
    "fact_price_daily": "price_date",
}


def fingerprint(con, schema: str, name: str, exclude_ids: list[int], cutoff: str, drop: set[str] = frozenset()) -> dict:
    cols = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = ? and table_name = ? order by ordinal_position",
        [schema, name],
    ).fetchall()
    exprs = []
    for col, dtype in cols:
        if col in drop:
            continue
        q = f'"{col}"'
        exprs.append(f"round({q}, 6)" if dtype in ("DOUBLE", "FLOAT", "REAL") else q)
    conds = []
    if name in LIVE:
        # DATE columns: complete UTC days before the cutoff only (a day still collecting readings is excluded)
        bound = f"cast('{cutoff}' as timestamptz)::date" if dict(cols).get(LIVE[name]) == "DATE" else f"'{cutoff}'"
        conds.append(f"\"{LIVE[name]}\" < {bound}")
    if exclude_ids and "steam_app_id" in [c for c, _ in cols]:
        conds.append(f"steam_app_id::bigint not in ({', '.join(map(str, exclude_ids))})")
    where = ("where " + " and ".join(conds)) if conds else ""
    n, fp = con.execute(
        f"select count(*), coalesce(sum(hash({', '.join(exprs)})::hugeint), 0)::varchar "
        f'from "{schema}"."{name}" {where}'
    ).fetchone()
    return {"rows": n, "fingerprint": fp, "cutoff": LIVE.get(name),
            **({"dropped_columns": sorted(drop)} if drop else {})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--diff")
    ap.add_argument("--only", nargs="*", help="restrict to these relations")
    ap.add_argument("--exclude-app-ids", nargs="*", type=int, default=[],
                    help="leave these games out (relations with a steam_app_id column)")
    ap.add_argument("--schemas", nargs="*", default=["main"], help="schemas to scan (default: main)")
    ap.add_argument("--cutoff", default=CUTOFF, help=f"cut for live relations (default {CUTOFF})")
    ap.add_argument("--rename", nargs="*", default=[], metavar="OLD=NEW",
                    help="with --diff: compare baseline relation OLD against current relation NEW")
    ap.add_argument("--drop-columns", nargs="*", default=[], metavar="TABLE.COLUMN",
                    help="leave these columns out of the fingerprint (e.g. columns added since the baseline)")
    args = ap.parse_args()

    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("set TimeZone = 'UTC'")
    con.execute("load httpfs")
    con.execute(f"set s3_region = '{os.environ['AWS_REGION']}'")
    con.execute(f"set s3_access_key_id = '{os.environ['AWS_ACCESS_KEY']}'")
    con.execute(f"set s3_secret_access_key = '{os.environ['AWS_SECRET_KEY']}'")
    if os.getenv("DATABASE_URL"):   # stg_ops__* views read the Neon logs through the same read-only attach as dbt
        con.execute("load postgres")
        con.execute("attach '" + os.environ["DATABASE_URL"].replace("'", "''") + "' as ops (type postgres, read_only)")

    rels = con.execute(
        f"select table_schema, table_name from information_schema.tables "
        f"where table_schema in ({', '.join('?' * len(args.schemas))}) order by 2",
        args.schemas,
    ).fetchall()
    if args.only:
        rels = [r for r in rels if r[1] in args.only]
    dupes = {n for _, n in rels if [m for _, m in rels].count(n) > 1}
    if dupes:
        print(f"relation names in more than one schema: {sorted(dupes)}", file=sys.stderr)
        return 1

    result = {}
    for schema, name in rels:
        drop = {c.split(".", 1)[1] for c in args.drop_columns if c.split(".", 1)[0] == name}
        result[name] = fingerprint(con, schema, name, args.exclude_app_ids, args.cutoff, drop)
        r = result[name]
        print(f"{name:<34} {r['rows']:>12,}  {r['fingerprint']}{'  (cut ' + r['cutoff'] + ')' if r['cutoff'] else ''}",
              flush=True)
    Path(args.out).write_text(json.dumps(result, indent=2))

    if args.diff:
        base = json.loads(Path(args.diff).read_text())
        renames = dict(r.split("=", 1) for r in args.rename)
        base = {renames.get(k, k): v for k, v in base.items()}
        changed = 0
        print("\nDiff vs", args.diff)
        for name in sorted(set(base) | set(result)):
            b, a = base.get(name), result.get(name)
            if not (b and a and (b["rows"], b["fingerprint"]) == (a["rows"], a["fingerprint"])):
                changed += 1
                print(f"  {name:<34} {b and b['rows']} -> {a and a['rows']}"
                      f"{'  (content changed)' if b and a and b['rows'] == a['rows'] else ''}")
        print(f"{changed} relation(s) differ" if changed else "identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
