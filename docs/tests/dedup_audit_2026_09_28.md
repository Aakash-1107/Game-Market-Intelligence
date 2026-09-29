# Step 1: Deduplication audit (2026-09-28)

Raw S3 stays append-only. All deduplication happens in staging: each model keeps the **latest fetch** per natural key, and a dbt test enforces the key.

## Per staging model

The **Duplicates before** column was measured on the baseline views.

| Staging model | Natural key (verified) | Latest-wins column | Duplicates before | Change | Test added |
|---|---|---|---|---|---|
| `stg_steam__player_counts` | `steam_app_id, recorded_at` (live ∪ backfill) | live `hourly` wins over `5min` backfill, then `filename` desc (names carry the run timestamp) | 0 (6,126,313 rows = distinct keys; live and backfill don't overlap) | `qualify` added; `read_parquet(…, filename = true)` | `unique_combination_of_columns` |
| `stg_steam__app_details` | `steam_app_id` | `fetched_at_utc` | 0 (already deduplicated) | none | `unique`, `not_null` |
| `stg_steam__reviews` | `steam_app_id, recommendation_id` | `fetched_at`, then within one fetch: `review_updated_at`, `playtime_forever`, `votes_up`, `weighted_vote_score` desc | **7,360** (55,000 rows, 47,640 keys) | `qualify` added | `unique_combination_of_columns`, `not_null(recommendation_id)` |
| `stg_steam__reviews_summary` | `steam_app_id` | `fetched_at` | 0 (one file per game so far) | `qualify` added | `unique`, `not_null` |
| review histogram | none | none | **no staging model exists.** 42 raw files (2026-09-23) in `raw/steam/review_histogram/` are not read by dbt | none | none |
| `stg_itad__price_history` | `itad_game_id, shop_id, observed_at` | `fetched_at_utc` (file level, newly extracted), then the existing artefact rule | **31** same-instant conflicts within one fetch (previously resolved in the mart) | `qualify` added | `unique_combination_of_columns` |
| `stg_steamcharts__monthly` | `steam_app_id, activity_month` | `fetched_at_utc` | 0 (already deduplicated) | none | `unique_combination_of_columns` |
| `stg_opencritic__reviews` | `review_id` | `fetched_at_utc` (deduplicated **before** the `en-us` / score filters, so a review is judged on its latest version) | 0 | `qualify` added | `unique` already existed |
| `stg_kaggle__steamcharts_monthly` | `steam_app_id, activity_month` | static file | 0 | none | `unique_combination_of_columns` |

### Disagreements with the expected keys

- **`stg_steam__reviews`.** The key was as expected. The expected cause was not: the duplicates didn't come from repeated runs. There was only one fetch file per game. They come from **Steam's cursor pagination repeating reviews across pages within a single fetch**, which the tie-break has to handle.
  - One game (1364780) had only 320 distinct reviews out of 1,000 rows.
  - 518 repeated reviews differ between pages, mostly in `playtime_forever`: the author kept playing between page requests.
  - The staging fix handles it. The root cause is in ingestion: `steam_reviews.py` uses the default `filter=all` (sorted by helpfulness). Steam's docs recommend `filter=recent` or `filter=updated` for cursor pagination. **Decided 2026-09-28: switched to `filter=recent`.** No deliberate refetch: the next run picks it up. A full refetch was started and then cancelled: 31 of 54 games (seed order, 570 … 892970) already have a `filter=recent` file from 2026-09-28 14:04–14:12 UTC. The rest pick it up on the next scheduled or manual run, and the Step 5 test game verifies it.
- **`stg_itad__price_history`.** The fetch timestamp is not in the records. It's the file-level `fetched_at_utc`, now extracted in staging. The same-instant tie-break from `fact_price_snapshot` moved into staging. The mart's `QUALIFY` stays as a no-op safeguard, with a comment.
- **`stg_steam__player_counts`.** There's no fetch timestamp in the Parquet files. The file name (for example `player_counts_20260928_1300.parquet`) serves as the tie-break. The one-off `player_counts_gap_recovery.parquet` sorts after timestamped names on the same day, which is harmless because both come from Neon.

## Mart checks

- **`fact_player_activity_monthly` (SteamCharts ∪ Kaggle):** no collision possible. `row_number() … partition by steam_app_id, activity_month order by source_priority` runs **before** the key is built, and `unique(activity_monthly_key)` already existed. It passes.
- **`fact_reviews` had no `unique` test on `review_key`.** The baseline had 54,000 rows but only 46,966 distinct keys. It now has `unique` and `not_null` tests.
- **The `fact_price_snapshot` drop from 56,139 to 54,893 is explained. It is not a duplicate issue.** 56,139 is the number of distinct `(itad_game_id, shop_id, observed_at)` keys. 56,139 − 54,893 = **1,246 = exactly the ITAD keys of Dying Light (239140)**. That game has price history but no appdetails, so the `dim_game` inner join removes it. This is the scope rule already documented in `fact_price_snapshot`.

## Row counts: baseline vs after Step 1

`dbt build`: `PASS=145 WARN=1 ERROR=0` (+12 new tests; same known WARN). Fingerprint diff (`exploration/fingerprints/step1_2026_09_28.json` vs baseline): **3 of 26 relations differ, all explained.**

| Relation | Baseline | After | Explanation |
|---|---:|---:|---|
| `stg_steam__reviews` | 55,000 | 47,640 | 7,360 repeated rows from pagination collapsed; 47,640 = distinct keys measured before the change |
| `fact_reviews` | 54,000 | 46,966 | Same fix downstream; 46,966 = distinct `review_key` measured on the baseline mart (47,640 − 674 Dying Light reviews) |
| `stg_itad__price_history` | 56,170 | 56,139 | 31 same-instant conflicts now resolved in staging. **`fact_price_snapshot` has an identical fingerprint**, so the rule matches the mart's |

The other 23 relations are identical, including all `an_*`, `dim_game`, `int_*` and the cut player-count models.

**Dashboard impact:** the Overview and Game Explorer pages count `fact_reviews`, so their review sample counts drop by about 13%. The lifetime review totals on `dim_game` don't change.
