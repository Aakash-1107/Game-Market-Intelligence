"""
Diagnostic: check how many of the 55 tracked games appear in
PlayerCountHistoryPart1 (5min) and PlayerCountHistoryPart2 (hourly).

Run from the project root:
    python src/utils/check_backfill_overlap.py
"""

from pathlib import Path
import duckdb

# --- Configuration ---
DUCKDB_PATH = r"C:\Users\isabe\Desktop\Weiterbildung\Capstone Project\data\game_market.duckdb"
PART1_DIR = Path(r"C:\Users\isabe\Downloads\PLayerCountData\PlayerCountHistoryPart1\PlayerCountHistoryPart1")
PART2_DIR = Path(r"C:\Users\isabe\Downloads\PLayerCountData\PlayerCountHistoryPart2\PlayerCountHistoryPart2")


def get_tracked_app_ids(duckdb_path: str) -> set[int]:
    con = duckdb.connect(duckdb_path)
    rows = con.execute(
        "SELECT DISTINCT CAST(steam_app_id AS INTEGER) "
        "FROM source_id_mappings"
    ).fetchall()
    con.close()
    return {row[0] for row in rows}


def get_app_ids_from_directory(directory: Path) -> dict[int, Path]:
    result = {}
    if not directory.exists():
        print(f"[WARN] Directory not found: {directory}")
        return result
    for filepath in directory.glob("*.csv"):
        stem = filepath.stem
        try:
            app_id = int(stem)
            result[app_id] = filepath
        except ValueError:
            print(f"[SKIP] Non-integer filename: {filepath.name}")
    return result


def report_overlap(label: str, tracked: set[int], available: dict[int, Path]) -> set[int]:
    matched = tracked & set(available.keys())
    print(f"\n--- {label} ---")
    print(f"  CSVs in directory  : {len(available):,}")
    print(f"  Tracked games      : {len(tracked)}")
    print(f"  Matched (overlap)  : {len(matched)}")
    print(f"  Not matched        : {len(tracked) - len(matched)}")

    if matched:
        print(f"\n  Matched App IDs:")
        for app_id in sorted(matched):
            print(f"    {app_id}  →  {available[app_id].name}")

    unmatched = tracked - set(available.keys())
    if unmatched:
        print(f"\n  Tracked but NOT in {label}:")
        for app_id in sorted(unmatched):
            print(f"    {app_id}")

    return matched


def main():
    print("Loading tracked App IDs from DuckDB...")
    tracked = get_tracked_app_ids(DUCKDB_PATH)
    print(f"Found {len(tracked)} tracked steam_app_ids.")

    part1_files = get_app_ids_from_directory(PART1_DIR)
    part2_files = get_app_ids_from_directory(PART2_DIR)

    matched_part1 = report_overlap("Part1 (5min, Dec 2017 – Aug 2020)", tracked, part1_files)
    matched_part2 = report_overlap("Part2 (hourly, Dec 2017 – Aug 2020)", tracked, part2_files)

    both = matched_part1 & matched_part2
    if both:
        print(f"\n[NOTE] {len(both)} game(s) appear in BOTH Part1 and Part2:")
        for app_id in sorted(both):
            print(f"  {app_id}")
        print("  → These will need resolution at load time (prefer Part1 for its finer resolution).")
    else:
        print(f"\n[OK] No overlap between Part1 and Part2 — datasets are disjoint.")

    print(f"\n=== Summary ===")
    print(f"  Part1 matches : {len(matched_part1)} / {len(tracked)}")
    print(f"  Part2 matches : {len(matched_part2)} / {len(tracked)}")
    print(f"  In both       : {len(both)}")


if __name__ == "__main__":
    main()