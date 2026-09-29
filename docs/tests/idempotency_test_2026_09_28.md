# Idempotency test (Step 2, 2026-09-28)

## What "idempotent" means here

Raw S3 is append-only, so a rerun always adds files. The pipeline is idempotent when **repeated raw files never add rows or change content**. The marts change only when the upstream API actually returned something new, such as a new review.

Because the reruns hit live APIs, the test checks two things:

1. **Games that were not rerun must be byte-identical.** This rules out any side effect.
2. **Games that were rerun** may change only by new upstream records or values, never by duplicates. Every difference has to be explained.

## Procedure (repeatable)

Run from the project root. Stop the dashboard first, because it holds the DuckDB lock.

```powershell
$G = "105600", "413150", "427520"     # Terraria, Stardew Valley, Factorio

# 0. Fingerprint the current build, full and with the test games excluded
python src/utils/fingerprint_models.py before_full.json
python src/utils/fingerprint_models.py before_excl.json --exclude-app-ids $G

# 1. Rerun ingestion for the subset (writes duplicate raw files to S3)
python src/ingestion/steam_reviews.py $G
python <itad subset helper> $G     # itad_price_history.py has no subset argument yet; the helper reuses its
                                  # get_itad_mappings / fetch_price_history / upload_to_s3 unchanged

# 2. Rebuild
cd game_market; dotenv -f ..\.env run -- dbt build; cd ..

# 3. Compare
python src/utils/fingerprint_models.py after_excl.json --exclude-app-ids $G --diff before_excl.json   # must be "identical"
python src/utils/fingerprint_models.py after_full.json --diff before_full.json                         # every diff explained
```

To repeat it, run steps 1–3 a second time and compare with the first run.

After Step 3 the ITAD script reads the seed, so its subset argument replaces the helper.

## Result

Both runs used the Step 1 code.

| | Reviews files | ITAD files | `dbt build` |
|---|---|---|---|
| Before | 1 per game (2026-09-22/25) | 1 per game (2026-09-20) | PASS=145 WARN=1 |
| Run 1 (13:51 UTC) | +1 per game | +1 per game | PASS=145 WARN=1 ERROR=0 |
| Run 2 (13:54 UTC) | +1 per game | +1 per game | PASS=145 WARN=1 ERROR=0 |

All `unique` tests on natural keys and surrogate keys passed after each run.

### Check 1: games not rerun (51 of 54)

`--exclude-app-ids 105600 413150 427520`: **identical** for all 26 relations after run 1.

### Check 2: all games

**Run 1 vs Step 1:**

| Relation | Before | After | Explanation |
|---|---:|---:|---|
| `fact_price_snapshot`, `stg_itad__price_history`, `int_price_daily`, `int_sale_episodes`, `an_sale_effect` | | **identical** | ITAD returned the same history, and the duplicate full-history files collapse completely |
| `stg_steam__reviews` | 47,640 | 48,032 | **+392 new keys**, each present only in the new fetch: 105600 +215, 413150 +119, 427520 +58. Steam's default review sample (sorted by helpfulness) is a different 1,000 each call. Keys from the older sample stay (latest-wins per key, not per file) |
| `fact_reviews` | 46,966 | 47,358 | Same +392 |
| `stg_steam__reviews_summary` | 55 | 55 | Content changed: new `fetched_at`, and lifetime totals moved since 2026-09-22/25 |
| `dim_game` | 54 | 54 | Content changed: the review-total columns for the 3 games |

**Run 2 vs run 1, 3 minutes apart:**

| Relation | Run 1 | Run 2 | Explanation |
|---|---:|---:|---|
| everything ITAD / price | | **identical** | third copy of the same history: no effect |
| `dim_game` | | **identical** | lifetime totals unchanged within 3 minutes |
| `stg_steam__reviews_summary` | 55 | 55 | only `fetched_at` changed (latest fetch wins) |
| `stg_steam__reviews` / `fact_reviews` | 48,032 / 47,358 | 48,060 / 47,386 | +28 new keys from sample drift. Row growth can only come from new keys, because the unique tests pass |

## Conclusion

- **Duplicate raw files have no effect:** ITAD was identical across three copies, and the 51 games not rerun were identical.
- **All remaining differences are new upstream data:** new review IDs from the reviews sample, and new lifetime totals.
- **Decided 2026-09-28:** `fact_reviews` keeps every review ever fetched, latest version per review. `steam_reviews.py` now uses `filter=recent` (newest 1,000, stable cursor pagination). A full refetch was started and then cancelled: 31 of 54 games (seed order, 570 … 892970) already have a `filter=recent` file from 2026-09-28 14:04–14:12 UTC. The rest pick it up on the next scheduled or manual run, and the Step 5 test game verifies it. Reviews fetched before 2026-09-28 remain a helpfulness-ordered sample (documented in `fact_reviews`' schema description).

Fingerprint files are in `exploration/fingerprints/` (gitignored, local only) (`step1_*`, `step2_run1_*`, `step2_run2_full.json`).
