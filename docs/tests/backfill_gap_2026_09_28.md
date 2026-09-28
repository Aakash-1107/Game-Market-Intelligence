# 5-minute backfill gap (found 2026-09-28)

**Status:** open. Deliberately **not fixed before the Sept 29 demo**.

**Plan:** backfill after the demo (Sept 29 evening) together with the Hollow Knight (367520) test, then re-validate Q3 (sale effect) and Q4 (unusual days).

## Finding

Eight active tracked games have complete data in PlayerCountHistoryPart1, but **no 5-minute backfill in S3**:

| steam_app_id | CSV rows (incl. header) | Range |
|---|---:|---|
| 394360 | 280,225 | 2017-12-14 00:00 – 2020-08-12 23:55 |
| 413150 | 280,225 | same |
| 427520 | 280,225 | same |
| 435150 | 280,225 | same |
| 489830 | 280,225 | same |
| 578080 | 280,225 | same |
| 588650 | 280,225 | same |
| 646570 | 280,225 | same |

- **The files are fine.** They have the same shape as backfilled games, for example 570 (Dota 2), and the same systematic zero at 2017-12-14 01:05.
- **Size of the gap:** roughly 8 × 280k ≈ 2.24M rows of `5min` data are missing from `fact_player_activity`.
- **Current coverage:** 22 backfill files exist in S3. That's 21 tracked games plus Dying Light (239140), which is no longer tracked.

## Cause

The 2026-09-22 backfill run (commit a5159fb) did **not** take its game list from `tracked_games`. It used:

```sql
SELECT DISTINCT CAST(steam_app_id AS INTEGER) FROM source_id_mappings
```

The stale `source_id_mappings` seed covered 39 app IDs and **none of these 8 games**. So the run matched only 22 dataset files, and it reported "22 of 55" coverage as if that were the dataset's limit.

`source_id_mappings.csv` was deleted on 2026-09-28. Since then, `backfill_player_counts.py` reads the active games from `tracked_games.csv` and skips games that already have a backfill in S3.

## How it was found

The Step 3b check compared S3 backfills against active games with a CSV in the dataset. It wrote nothing:

- in S3: 22
- active games with a CSV: 29
- CSV but not in S3: the 8 above

## Fix (after the demo)

```powershell
python src/ingestion/backfill_player_counts.py 394360 413150 427520 435150 489830 578080 588650 646570 367520
cd game_market; dotenv -f ..\.env run -- dbt build; cd ..
```

The script is safe to rerun: existing backfills are skipped.

**Expected impact:**
- **Grows:** `stg_steam__player_counts`, `fact_player_activity`, `int_player_activity_daily`.
- **May change:** `an_sale_effect` and `an_market_anomalies`. Their baselines and z-scores for 2017–2020 get denser data.
- **Probably unchanged:** `int_game_first_observed`. It takes the minimum of this data and the monthly history, which already starts earlier for these games, and nothing downstream reads it.
- **Unaffected:** the monthly models and `an_game_lifecycle` / `an_activity_health`, which use monthly data.

Re-validate Q3 and Q4 on the dashboard afterwards, and diff with `src/utils/fingerprint_models.py`.
