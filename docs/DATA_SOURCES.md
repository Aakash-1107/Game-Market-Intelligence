# Data sources and the public snapshot

Data collection ran from **13 Sep 2026, 16:29 UTC (first reading) to 7 Oct 2026, 14:47 UTC (final reading)** and is now frozen. The results are published as a
read-only DuckDB file (the *snapshot*) attached to the GitHub Release
[data-2026-10-07](https://github.com/Aakash-1107/Game-Market-Intelligence/releases/tag/data-2026-10-07), and the hosted
dashboard reads that file. How to open it: [RUNBOOK.md, A0](RUNBOOK.md#a0-explore-the-results-without-credentials). The
code in this repository still runs for anyone who wants to collect their own data (RUNBOOK Part A).

## Sources and attribution

| Source | What it provides | Terms | In the snapshot |
|---|---|---|---|
| Steam (Valve): Web API and Store API | Hourly player counts (collected by this project), game details, review votes and playtime at review | Steam API terms. Data powered by Steam. Not affiliated with or endorsed by Valve. Steam and the Steam logo are trademarks of Valve Corporation | Yes, without review text and without review or reviewer identifiers |
| [IsThereAnyDeal](https://isthereanydeal.com) | Price and discount history (Steam and other shops) | IsThereAnyDeal API terms | Yes, price values unchanged |
| [SteamCharts](https://steamcharts.com) | Monthly average and peak players | Public website | Yes, monthly values (every month in `fact_player_activity_monthly`) |
| Mendeley Data: "Steam Games Dataset: Player count history, Price history and data about games" ([doi:10.17632/ycy3sy3vj2.1](https://doi.org/10.17632/ycy3sy3vj2.1)) | 5-minute player counts, Dec 2017 to Aug 2020, for 29 of the tracked games | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Only aggregated: daily values and the analyses built on them. The 5-minute rows are not included |
| Kaggle: "Steam Monthly Average Players" by Victor Laputsky | Monthly players up to Sept 2025 | CC0 | No rows. Validation source only: SteamCharts covers every month, so the fallback in `int_player_activity_monthly__merged` never used it |
| OpenCritic (via RapidAPI) | Critic scores (manual, optional) | RapidAPI / OpenCritic terms | No |

## What the snapshot contains

`game_market_snapshot.duckdb`, built by [src/utils/build_snapshot.py](../src/utils/build_snapshot.py) from the full
warehouse. Same schema and table names as the warehouse, so queries on these tables run unchanged against either file:

- `marts`: `dim_game`, `fact_player_activity` (hourly rows only), `fact_player_activity_daily`,
  `fact_player_activity_monthly`, `fact_price_snapshot`, `fact_price_daily`, `fact_discount_episode`, `fact_reviews`
  (only `game_key`, `steam_app_id`, `voted_up`, `playtime_at_review_minutes`)
- `reporting`: every `rpt_*` table (the four analytical questions)
- `observability.mart_ingestion_daily`: this project's own collection completeness per day
- `meta.snapshot_info`: build time, collection window, git commit, row count per table, attribution

## What it leaves out

- Review text, reviewer IDs and review IDs (never stored in the warehouse's analytical layers; review IDs are dropped
  from the snapshot)
- Raw files, the staging and intermediate layers, and the pipeline logs
- OpenCritic data (`fact_critic_review`)
- The 5-minute rows of the Mendeley dataset (only their daily aggregates are included)
