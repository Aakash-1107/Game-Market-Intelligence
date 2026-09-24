# Handoff results 2026-09-24: SteamCharts monthly merge + Q1 rebuild

> Note: `handoff_2026_09_24.md` ends mid-sentence in the "Results file" section
> ("1. Task 0 audit findings (misplacements found/removed,"). Everything after that
> is missing, so this file covers each task's outcome in order.

## Summary

| Task | Status |
|---|---|
| 0 Audit | Done. 1 misplacement removed; 1 YAML syntax error found (fixed in Task 2) |
| 1 Move probe script | Already done: file was already at `exploration/steamcharts_probe.py`, untracked, not in `src/ingestion/` |
| 2 Source definition | Done. `steamcharts_raw` was already present; repaired a truncated string in `kaggle_raw` |
| 3 Staging model | Done. SQL already matched the spec; schema block updated to the spec |
| 4 Fact model | Done. Replaced with the handoff SQL |
| 5 Fact schema | Done. New block appended (no existing block); `dbt parse` clean |
| 6 Build | Done. PASS=35 WARN=0 ERROR=0 |
| 7 Reconciliation | Done. 3603/3603 within 1%, max_rel_diff 0 |
| 8 Post-build checks | Done. See results and deviations below |

Nothing was committed or pushed. Nothing in `src/ingestion/` was run. `an_game_lifecycle.sql` was not edited.

## Task 0: Audit

**yml search (`game_market/models/**/*.yml`)**
- `- name: source` under `fact_critic_review`: **found** at `models/marts/schema.yml` (old lines 111-116, with a `not_null` test and `accepted_values ['steamcharts','kaggle']`). **Removed.**
- Existing `- name: fact_player_activity_monthly` block: **none** in any yml file.
- Duplicate model names across yml files: **none**. Model blocks: staging/schema.yml (4), marts/schema.yml (4), intermediate/_intermediate__models.yml (3), analytics/schema.yml (1), analytics/_analytics__models.yml (1).

**`dbt parse` (before any changes): FAILED**
```
Parsing Error
  Error reading game_market: staging\sources.yml - Runtime Error
    Syntax error near line 88
    while parsing a block mapping in line 81, column 13
    did not find expected key in line 88, column 31
```
Cause: the `kaggle_raw.steamcharts_monthly.month` column description had been cut off, leaving an unterminated string (`"Text month-year like 'Sep-25' — parsed to date in stagi`). The committed version ends `...in staging"`. Fixed in Task 2 (same file) by restoring the committed text.

**Other observations (reported, not changed)**
- `staging/sources.yml` line 6, under `steam_raw`: comment `# DELETE the meta block below — it overrides the table-level external locations`. `steam_raw` has no meta block, so the comment is stale or misleading. Left as is.
- `staging/schema.yml` mixes the `tests:` key (older models) with `data_tests:` (new block). Both parse in dbt 1.12. `marts/schema.yml` has the same mix. A full re-parse (`dbt parse --no-partial-parse --show-all-deprecations`) reports 14 `MissingArgumentsPropertyInGenericTestDeprecation` warnings. They come from existing tests (for example `relationships`, `accepted_values` and `dbt_utils.accepted_range` on `fact_critic_review`, `dim_game`/`fact_*` and `stg_opencritic__reviews`) that pass test arguments directly instead of nesting them under `arguments:`. These are warnings only, not errors, and they predate this handoff.
- `stg_steamcharts__monthly` already had a schema block (without a description, using `tests:`). The uncommitted working-tree changes in schema.yml and sources.yml predate this session.

## Task 1: Move probe script
`src/ingestion/steamcharts_probe.py` does not exist. The file is already at `exploration/steamcharts_probe.py` and git has never tracked it, so no move was needed.

## Task 2: Source definition
The `steamcharts_raw` entry was already in `sources.yml`, matching the spec and the `kaggle_raw` style (table-level `meta.external_location`). The only change was repairing the truncated `month` description noted in Task 0. The 4-level wildcard `monthly/*/*/*/*.parquet` matches `monthly/2026/09/24/<file>.parquet`, and the build found the files.

## Task 3: Staging model
`stg_steamcharts__monthly.sql` already existed and matches the spec apart from column-alignment whitespace, so it was not changed. In the `staging/schema.yml` block, I added the description and switched `tests:` to `data_tests:`, as specified.

## Task 4 / 5: Fact model and schema
- `models/marts/fact_player_activity_monthly.sql`: full content replaced with the handoff SQL.
- `models/marts/schema.yml`: new `fact_player_activity_monthly` block appended at model level, with 5 columns and tests as specified.
- `dbt parse` afterwards: **no errors, no warnings.**

## Task 6: Build
`dbt build --select stg_steamcharts__monthly+ stg_kaggle__steamcharts_monthly+`
```
Finished running 5 table models, 28 data tests, 2 view models in 8.97s
Done. PASS=35 WARN=0 ERROR=0 SKIP=0
```
Rebuilt: both staging views, `fact_player_activity_monthly`, `int_game_first_observed`, `int_player_activity_lifecycle`, `an_game_lifecycle`, and also `game_trajectory_monthly`, which is downstream but was not in the expected list. All its tests pass.

## Task 7: Reconciliation (months before 2025-09, games in dim_game)

| overlapping_months | within_1pct | max_rel_diff |
|---:|---:|---:|
| 3603 | 3603 | 0 |

The two sources agree exactly on every overlapping month, which confirms they share the same underlying data.

## Task 8: Post-build checks

**Rows by source**

| source | rows | games |
|---|---:|---:|
| steamcharts | 4858 | 52 |

Kaggle contributes **0 rows**: SteamCharts covers every game-month that Kaggle has for these games. There are 52 games in the fact table and 54 in `dim_game`. The two without data (Onimusha: Way of the Sword and The Blood of Dawnwalker) have no monthly data (`no_monthly_data`).

**Games with gaps (span > months)**

| game | months | span | missing months |
|---|---:|---:|---|
| Cities: Skylines | 139 | 145 | 2014-09 … 2015-02 |
| Stellaris | 127 | 133 | 2015-09 … 2016-02 |
| Slay the Spire | 110 | 111 | 2017-08 |

All three gaps are before release (Cities: Skylines released 2015-03, Stellaris 2016-05, Slay the Spire early access 2017-11). The earliest row for each is therefore probably an isolated pre-release month on SteamCharts, not missing post-launch data. If these stray rows fall inside the lifecycle's launch window, they could affect launch detection. Not investigated further (out of scope).

**Lifecycle distribution**

| lifecycle_status | lifecycle_pattern | games |
|---|---|---:|
| launch_not_observed | – | 2 |
| launch_observed | front_loaded | 14 |
| launch_observed | gradual_decline | 5 |
| launch_observed | growing | 12 |
| launch_observed | insufficient_history | 8 |
| launch_observed | sustained | 10 |
| no_monthly_data | – | 2 |
| released_after_coverage | – | 1 |

`launch_observed` = **49** (was 27; the handoff expected about 45). Non-observed games: Terraria and Euro Truck Simulator 2 (`launch_not_observed`, plausible since both released before SteamCharts coverage), Onimusha: Way of the Sword and The Blood of Dawnwalker (`no_monthly_data`), and Valheim (`released_after_coverage`).

**launch_observed detail (CSV)**
```
name,launch_type,launch_peak,lp_idx,r12,low,has_recovery,rec_ratio,new_high,lifecycle_pattern
"Baldur's Gate 3",fresh_launch,450982.0,0,0.15,0.09,false,1.3,false,front_loaded
Cities: Skylines,fresh_launch,26185.0,0,0.25,0.18,true,4.4,false,front_loaded
Cyberpunk 2077,fresh_launch,332396.0,0,0.05,0.02,false,8.0,false,front_loaded
"DARK SOULS™ III",fresh_launch,74267.0,0,0.25,0.04,false,2.8,false,front_loaded
ELDEN RING,fresh_launch,522066.0,1,0.1,0.04,false,8.1,false,front_loaded
Fallout 4,fresh_launch,226298.0,0,0.09,0.05,false,5.5,false,front_loaded
"HELLDIVERS™ 2",fresh_launch,274304.0,0,0.19,0.08,false,2.4,false,front_loaded
Marvel Rivals,fresh_launch,306066.0,1,0.25,0.21,false,1.3,false,front_loaded
Monster Hunter Wilds,fresh_launch,318011.0,1,0.09,0.03,false,2.2,false,front_loaded
"No Man's Sky",fresh_launch,36976.0,0,0.13,0.01,true,55.7,true,front_loaded
PUBG: BATTLEGROUNDS,pre_release_base,1584887.0,1,0.3,0.09,false,2.4,false,front_loaded
Path of Exile 2,fresh_launch,304199.0,0,0.26,0.02,false,12.6,false,front_loaded
Stardew Valley,fresh_launch,34947.0,1,0.28,0.13,true,22.2,true,front_loaded
The Witcher 3: Wild Hunt - Complete Edition,fresh_launch,51917.0,0,0.18,0.1,false,6.7,false,front_loaded
Dead Cells,pre_release_base,4438.0,0,0.46,0.25,true,4.5,true,gradual_decline
Divinity: Original Sin 2 - Definitive Edition,fresh_launch,28003.0,1,0.41,0.11,false,3.5,false,gradual_decline
Path of Exile,fresh_launch,19347.0,0,0.3,0.2,true,11.4,true,gradual_decline
Subnautica,pre_release_base,17322.0,1,0.3,0.1,false,7.3,true,gradual_decline
The Elder Scrolls V: Skyrim Special Edition,fresh_launch,28054.0,1,0.34,0.27,true,3.6,true,gradual_decline
"Apex Legends™",fresh_launch,120983.0,3,1.13,0.58,false,NULL,true,growing
Counter-Strike 2,fresh_launch,16001.0,1,1.62,0.67,false,NULL,true,growing
DayZ,pre_release_base,7886.0,0,1.59,0.62,false,NULL,true,growing
Dota 2,pre_release_base,330720.0,1,1.62,0.94,false,NULL,true,growing
FINAL FANTASY XIV Online,fresh_launch,3578.0,0,1.16,0.52,false,NULL,true,growing
"Overwatch®",fresh_launch,28327.0,0,1.22,0.63,false,NULL,true,growing
Rust,pre_release_base,33507.0,0,1.27,0.71,false,NULL,true,growing
Slay the Spire,pre_release_base,10407.0,0,1.05,0.48,true,4.6,true,growing
"The Sims™ 4",fresh_launch,4182.0,3,1.94,0.62,false,NULL,true,growing
"Tom Clancy's Rainbow Six Siege",fresh_launch,10244.0,1,1.68,0.6,false,NULL,true,growing
War Thunder,fresh_launch,7587.0,1,1.0,0.72,false,NULL,true,growing
Warframe,fresh_launch,12330.0,1,1.0,0.72,false,NULL,true,growing
"Battlefield™ 6",fresh_launch,311140.0,0,NULL,0.1,false,1.2,false,insufficient_history
Crimson Desert Enhanced,fresh_launch,166396.0,0,NULL,0.07,false,0.3,false,insufficient_history
"EA SPORTS FC™ 26",fresh_launch,45051.0,1,NULL,0.84,false,NULL,false,insufficient_history
Escape from Tarkov,fresh_launch,27105.0,0,NULL,0.42,true,1.8,false,insufficient_history
Forza Horizon 6,fresh_launch,198633.0,0,NULL,0.1,false,NULL,false,insufficient_history
How to Fish,fresh_launch,148647.0,0,NULL,NULL,false,NULL,NULL,insufficient_history
Palworld,pre_release_base,404614.0,0,NULL,0.6,false,NULL,false,insufficient_history
TBH: Task Bar Hero,fresh_launch,434627.0,1,NULL,0.25,false,NULL,false,insufficient_history
7 Days to Die,pre_release_base,58564.0,1,0.77,0.33,false,1.5,false,sustained
Bongo Cat,fresh_launch,151351.0,3,0.86,0.52,false,NULL,true,sustained
Factorio,pre_release_base,16466.0,1,0.66,0.58,false,NULL,true,sustained
Grand Theft Auto V Enhanced,fresh_launch,75294.0,0,0.68,0.49,true,1.8,false,sustained
Hearts of Iron IV,fresh_launch,12326.0,0,0.83,0.4,true,8.1,true,sustained
PAYDAY 2,fresh_launch,16650.0,0,0.82,0.3,true,12.0,true,sustained
Red Dead Redemption 2,fresh_launch,28626.0,0,0.6,0.4,true,3.6,true,sustained
RimWorld,pre_release_base,13298.0,1,0.76,0.75,false,NULL,true,sustained
Stellaris,fresh_launch,20800.0,0,0.68,0.21,true,4.6,true,sustained
"Street Fighter™ 6",fresh_launch,34149.0,0,0.61,0.33,false,1.7,false,sustained
```

## Deviations from expectations / items for review (not fixed; outside scope)
1. **launch_observed = 49 vs about 45 expected.** Every model and test passes; the difference comes from the data. Worth checking whether the 4 extra games were expected.
2. **Kaggle rows = 0.** Expected "few/no rows", so this is consistent. Kaggle currently adds nothing to this game set; it only matters if games are added that SteamCharts lacks.
3. **Valheim = `released_after_coverage`.** Valheim has 67 monthly rows (2021-02 to 2026-08), but `dim_game.release_date` = **2026-09-09**, probably the 1.0 / out-of-early-access date from Steam app details. The lifecycle therefore treats it as released after coverage and ignores its early-access launch in Feb 2021. The fix belongs in `dim_game` (release date / early-access handling) or in how `an_game_lifecycle` picks its launch date, not in this handoff's models.
4. **Possibly odd launch values:** FINAL FANTASY XIV Online `fresh_launch` with launch_peak 3578 (the Steam listing came long after the game's original launch). The Sims™ 4 and Apex Legends™ have launch_peak_month_index 3. Crimson Desert Enhanced has rec_ratio 0.3 (< 1), which looks inconsistent with a "recovery ratio". How to Fish has NULL `low`/`new_high`. All are for review, not errors.
5. **Stray pre-release months** for Cities: Skylines, Stellaris and Slay the Spire (see gap table).
6. **Stale comment** `# DELETE the meta block below …` in `staging/sources.yml` under `steam_raw`. Removed later at the user's request.

## Files changed this session
- `game_market/models/marts/schema.yml`: removed the misplaced `source` block from `fact_critic_review`; added the `fact_player_activity_monthly` block.
- `game_market/models/staging/sources.yml`: repaired the truncated `kaggle_raw` month description (the `steamcharts_raw` entry was already present).
- `game_market/models/staging/schema.yml`: `stg_steamcharts__monthly` block now has the description and `data_tests:`.
- `game_market/models/marts/fact_player_activity_monthly.sql`: replaced with the handoff SQL.
- `exploration/handoff_results.md`: this file.
