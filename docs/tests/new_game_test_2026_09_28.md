# Step 5: end-to-end new-game test with Hades (2026-09-28)

**Result:** adding **one row** to `tracked_games.csv` was enough. Hades (1145360) got details, an ITAD ID, prices, monthly history and reviews, and it appears in the Game Explorer. Nothing changed for the other 54 games.

- **As expected:** no hourly activity yet (that comes after the merge) and no 5-minute backfill.
- **One deviation:** the in-flow `dbt build` ran out of memory, so the final `dbt build` ran by hand, per the 19:00 fallback. Details are in the Step 4 report.

## Procedure

0. Took a DuckDB snapshot (Ash).
1. Took the "before" fingerprint of the current build, which contains the 54 games: `exploration/fingerprints/pre_hades_2026_09_28.json`.
2. **Added `1145360,Hades,true` to `game_market/seeds/tracked_games.csv`. That was the only edit.**
   - My first append used an LF ending on a file checked out with CRLF (`core.autocrlf=true`). DuckDB's CSV sniffer rejects mixed line endings, so the seed failed to load.
   - The file was normalised to LF and the git diff is the single added line.
   - Someone editing the file in an editor won't hit this. A script appending to it can.
3. Ran `python flows/daily_market_refresh.py 1145360`, twice (the first run hit the seed error above). The ingestion part succeeded both times:

   | Task | Result |
   |---|---|
   | resolve_ids | matched_auto → `018d937f-33f0-7200-80fc-87f769196c84` |
   | prices | 263 records |
   | app_details | ok |
   | reviews | ok (1,000 per fetch) |
   | steamcharts_monthly | ok |
   | freshness | ok |
   | dbt_build | **failed: DuckDB out of memory** (`stg_steam__app_details`) |

4. Ran `python src/ingestion/backfill_player_counts.py 1145360`. Result: `no_coverage: not in PlayerCountHistoryPart1`, logged to `ingestion_log`, as expected.
5. Ran `dbt build --threads 1` standalone. Result: **`PASS=157 WARN=0 ERROR=0`**. The warn test `game_coverage.in_dim_game` passes, so Hades is in `dim_game`.

## `game_coverage` for Hades

| Flag | Value | |
|---|---|---|
| is_active / in_dim_game | true / true | |
| has_details | **true** | release 2020-09-17, paid, 154,115 lifetime reviews, 98.39 % positive |
| has_itad_id | **true** | `matched_auto` |
| has_prices | **true** | 263 events 2018-12-08 → 2026-09-25, 107 of them on Steam |
| has_monthly_activity | **true** | 81 months, 2019-12 → 2026-08, all from SteamCharts (priority over Kaggle) |
| has_reviews | **true** | 1,003 reviews, created 2026-08-02 → 2026-09-28: newest-first (`filter=recent`) verified on a game fetched only with it. Two flow runs a few minutes apart gave 1,000 + 3 new reviews |
| has_hourly_activity | **false (expected)** | the scheduled hourly deployment clones `main`, so it sees Hades only after this branch is merged and pushed. **To verify after the merge:** the next hourly run includes Hades, and `has_hourly_activity` turns true |
| has_5min_backfill | false (expected) | Hades isn't in the dataset (`no_coverage` logged) |
| has_critic_reviews | false (by design) | OpenCritic is manual-only and Hades has no override row |

## Game Explorer

I checked this with Streamlit's `AppTest`, which runs `dashboard/views/5_Game_Explorer.py` headless:
- Hades is in the game list (55 games).
- Selecting it raises **no exceptions**, and the page shows its subheader and metrics: "Busiest month ever: 19,587", "Positive reviews: 97%", "Players online now: —".
- The "—" is correct without hourly data, and the hourly chart is skipped because the page only draws it with at least 24 readings.

`AppTest` can't inspect Plotly charts, so **the charts haven't been checked visually**. Please take a quick look in the browser.

## The other 54 games

```
python src/utils/fingerprint_models.py post.json --exclude-app-ids 1145360 --diff pre_hades_2026_09_28.json
  game_coverage   54 -> 54 (content changed)
1 relation(s) differ
```

**All other relations are identical for the 54 games.** That covers every staging model, fact, `dim_game`, `int_*`, the `an_*` models (including `an_activity_health`'s cross-game rank) and the seeds.

The `game_coverage` change is live hourly data, not a side effect of adding Hades:
- The scheduled hourly run at 16:01 UTC landed between the two builds and added **exactly one reading per game (54 rows)**.
- That moved `hourly_rows` and `last_hourly_at` for all 54.
- `game_coverage` has no date column for the fingerprint tool's cutoff, so live changes show up in it. That's a small gap in the tool.

## Decision for Ash

Keep Hades tracked, or set `is_active=false`? Its raw files stay in S3 either way.
