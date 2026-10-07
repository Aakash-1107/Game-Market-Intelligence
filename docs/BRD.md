# Business Requirements Document (BRD)

## PC Game Market & Activity Intelligence

Data collection frozen on 2026-10-07; the published snapshot and the hosted dashboard show the final state.

| | |
|---|---|
| Version | 2.1 |
| Date | 2026-10-07 |
| Author | Aakash |
| Status | Describes the implemented system; collection frozen, results from the published snapshot of 2026-10-07 |
| Companion documents | [TRD](TRD.md) (how it is built), [ANALYTICS.md](ANALYTICS.md) (metric definitions and results), [RUNBOOK.md](RUNBOOK.md) (use and operation) |

This document states **what** the system must deliver and **why**. How it is built is in the TRD. Metric formulas and
results are in [ANALYTICS.md](ANALYTICS.md) and are not repeated here.

---

## 1. Purpose

Provide a reproducible data pipeline that turns public data about PC games on Steam (player counts, prices,
discounts, game details, reviews) into tested analytical tables and a dashboard that answer the four questions in
section 3.

## 2. Problem

Steam does not publish player-count history, and price history, monthly player history and review data sit in
separate places with different identifiers. Anyone who wants to relate a game's player activity to its age or its
discounts must first collect, align and clean these sources. This project does that once, keeps the raw data, and
exposes one consistent set of tables.

## 3. Business questions

Every requirement in this document exists to answer one of these four questions.

| ID | Question | Output the user receives |
|---|---|---|
| Q1 | **Life after launch.** How do games gain, lose, retain and recover players after release? | For each game, monthly average players as a percentage of its launch peak for months 0 to 24; retention at 6, 12 and 24 months; one lifecycle pattern per game; the typical curve across games |
| Q2 | **Activity health.** Can a stable game be told apart from a declining one when both have a similar current player count? | For each game, the 12-month change in players, the monthly trend, and one class: growing, declining, stable or volatile |
| Q3 | **Discounts.** After a discount ends, do a game's players stay above their pre-discount level or return to it? | For each discount, players during it and 1 to 4 weeks after it, relative to the 14 days before it; the share of discounts by outcome |
| Q4 | **Unusual days.** Which days show abnormal activity for a game, and do they coincide with discounts or with activity across Steam? | A list of flagged days per game with the expected range, a marker for days flagged across several games at once, and the rate of flagged days by discount depth |

Results are **descriptive and associational**. The system reports what coincided with what. It makes no causal
claims, and no output or document may state that a discount caused a change in players. Coverage and results per
question: [ANALYTICS.md, Results](ANALYTICS.md#results).

## 4. Users

| User | Decision the system supports | Questions |
|---|---|---|
| Publisher or marketing analyst | Whether a discount leaves players above their previous level | Q3, Q4 |
| Developer or studio | What player retention after launch looks like for comparable games | Q1, Q2 |
| Market analyst | Which games are growing, declining or showing unusual activity | Q2, Q4 |
| Data analyst or student | Querying the tables directly with SQL for their own questions | all |

## 5. Scope

### 5.1 In scope

| ID | Requirement | Acceptance criterion |
|---|---|---|
| BR-1 | Collect the current concurrent player count of every active tracked game every hour | One reading per active game per hour in raw storage, with a log entry for each attempt |
| BR-2 | Obtain price and discount history for every tracked game | Daily Steam price and discount periods per game, back to the start of the source's history |
| BR-3 | Obtain monthly average and peak players for every tracked game | Monthly series from 2012 where a source has it |
| BR-4 | Obtain 5-minute player history where a public dataset has it | 5-minute series for tracked games present in the dataset, Dec 2017 to Aug 2020 |
| BR-5 | Obtain game details: release date, genres, developers, publishers, platforms | One record per game in the game dimension |
| BR-6 | Obtain player reviews (newest 1,000 English reviews per game) and, for a limited set, critic reviews | Review facts joined to the game dimension |
| BR-7 | Keep every raw response unchanged so any result can be recomputed without calling a source again | Raw files are append-only; a full model rebuild from raw files completes without any API call |
| BR-8 | Detect bad or missing data and report pipeline health without stopping the pipeline | Automated tests in every build; a health status per data source that answers "is it healthy now, and where did it fail" |
| BR-9 | Add a game by changing one row of one file | Verified: [tests/new_game_test_2026_09_28.md](tests/new_game_test_2026_09_28.md) |
| BR-10 | Serve Q1 to Q4 and the pipeline health through a dashboard that reads only the analytical tables | One page per question, a market overview, a game explorer, a data page and a pipeline health page |
| BR-11 | Let a third party reproduce the pipeline and query the data | [RUNBOOK.md](RUNBOOK.md) Part A takes a fresh clone to a first query |

### 5.2 Out of scope

| Item | Reason |
|---|---|
| Console and mobile platforms | Steam is PC only |
| Wishlist, sales volume and demographic data | No public source |
| Regional price comparison | Prices are collected for one country (Germany) |
| Real-time or streaming processing | Questions need hourly to daily resolution; batch is sufficient |
| Steam news, patch notes and text analysis of reviews | No question requires them |
| Social media and video-platform activity | No question requires it |
| Causal inference | Methodology not designed; see section 3 |
| Machine learning | No question requires it |
| The full Steam catalogue | The system tracks a chosen list of games |

## 6. Tracked games

- The tracked list is the file `game_market/seeds/tracked_games.csv`: 55 active games.
- Selection criterion: variety of release age, genre, business model (paid, free-to-play) and discount behaviour.
  Games with 5-minute history in the Mendeley dataset were preferred, because only they can answer Q3 and Q4.
- A game enters scope when it is in the list **and** Steam returns details for it.
- Setting `is_active` to `false` stops collection and keeps the game's history.

## 7. Data requirements

What the system must hold, per business need. The sources that supply it and their technical details are in
[TRD section 3](TRD.md#3-source-specification).

| Need | Required for | Resolution | History required |
|---|---|---|---|
| Concurrent players | Q1 to Q4 | 5-minute (Dec 2017 to Aug 2020), hourly (collection window), monthly (2012 onward) | As long as available |
| Steam price and discount periods | Q3, Q4 | Daily | As long as available |
| Game details | all (scope, release date, genre) | Current snapshot | Current |
| Player reviews | Game explorer | Per review | Newest 1,000 per game |
| Critic reviews | Game explorer | Per review | 12 games |

Which question uses which resolution:

- Q1 and Q2 use monthly player data.
- Q3 and Q4 use 5-minute data, because they need complete days and a 14-day or 28-day baseline.
- Hourly data is collected for current monitoring and for later analysis.

## 8. Coverage limits of the answers

These limits come from the available data. They are not defects of the pipeline.

| Limit | Effect |
|---|---|
| Steam has no history endpoint for current players | Hourly data exists only for the collection window (13 Sep 2026, 16:29 UTC to 7 Oct 2026, 14:47 UTC). A missed hour cannot be recovered; the gaps are listed in [TRD section 13.1](TRD.md#131-collection-incidents) |
| 5-minute history covers Dec 2017 to Aug 2020 and only games in the Mendeley dataset | Q3 covers 23 games and Q4 covers 29 games. Between Aug 2020 and the start of hourly collection only monthly averages exist |
| The review fetch returns the newest 1,000 reviews per game | Older reviews are absent. Reviews fetched before 2026-09-28 are a helpfulness-ordered sample |
| OpenCritic access is quota-limited | Critic reviews exist for 12 of 55 games |
| Findings are pooled across games in three places (Q3 outcome shares and depth cards, Q4 surge ratio) | Games with many discounts or flagged days weigh more ([ANALYTICS.md, Notes](ANALYTICS.md#notes)) |

## 9. Success criteria

| # | Criterion | Measure | Result |
|---|---|---|---|
| 1 | Data from at least three external sources is ingested without manual steps | Sources collected by the scheduled or daily flows | Met: Steam (3 endpoints), IsThereAnyDeal, SteamCharts |
| 2 | Q1 to Q4 are answered from the data | One reporting model per question, with the coverage in [ANALYTICS.md](ANALYTICS.md#results) | Met |
| 3 | All data tests pass | `dbt build` | Met on 2026-09-29: 224 nodes passed, 0 errors ([observability test](tests/observability_2026_09_29.md)) |
| 4 | Duplicates cannot enter the models | Uniqueness test on every natural key | Met: the audit found and removed 7,034 duplicate reviews (13% of the table) ([dedup audit](tests/dedup_audit_2026_09_28.md)) |
| 5 | A rerun does not change results | Idempotency test | Met: [tests/idempotency_test_2026_09_28.md](tests/idempotency_test_2026_09_28.md) |
| 6 | A failed source is visible and does not corrupt models | Pipeline health view; `dbt build` is skipped when an upstream task failed | Met |
| 7 | Adding a game needs one row | BR-9 | Met |
| 8 | A third party can reproduce the pipeline | BR-11 | Met, with the one-time inputs listed in RUNBOOK A4 |

## 10. Constraints and assumptions

**Constraints**

- Budget: free tiers and open-source tools only.
- Steam endpoints are rate limited; the pipeline must pace its requests (limits and pacing in the TRD).
- Scraping is allowed only where the site permits it; the SteamCharts script checks `robots.txt` before it runs.
- Raw data belongs to its providers and is not stored in the repository ([DATA_SOURCES.md](DATA_SOURCES.md)).

**Assumptions**

- Steam keeps the used endpoints available without a key.
- IsThereAnyDeal keeps its free API tier.
- A concurrent player count read once per hour is representative enough for monthly and daily averages.

## 11. Document history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09 | Requirements written before implementation |
| 2.0 | 2026-10-02 | Rewritten to match the implemented system: four questions renumbered (Q1 life after launch, Q2 activity health, Q3 discounts, Q4 unusual days); removed the supporting questions Q5 to Q7, RAWG, per-game catalogue table, and all open or conditional statements |
| 2.1 | 2026-10-07 | Collection frozen. Results moved to ANALYTICS.md and taken from the published snapshot; removed the unverified ITAD coverage limit |
