# Business Requirements Document (BRD)
## Game Market Intelligence & Player Activity

**Version:** 1.0
**Date:** September 2026
**Author:** Aakash

---

## 1. Executive Summary

This project delivers a data engineering platform that ingests, transforms, and analyses data from the PC gaming market. It combines game pricing and discount history, player engagement over time, and critic and player sentiment to answer four primary downstream questions about how games acquire, retain, and lose player activity — and whether pricing events produce lasting behavioural change. The platform is designed as a practical data engineering system in which ingestion, transformation, analytical modelling, testing, and serving are selected to match the project's actual data volume, update frequency, and downstream questions.

---

## 2. Business Context & Problem Statement

The PC gaming market operates on seasonal sale cycles, viral growth events, and long post-launch lifecycles that monthly data cannot fully capture. Developers, publishers, and market analysts lack an integrated tool that connects pricing history, player count trajectory, sentiment signals, and game quality indicators into a single queryable analytical layer.

This project addresses that gap by building a pipeline that:

- Tracks the full lifecycle of player activity from launch through long-term retention or decline
- Measures how pricing events (sales, discounts) affect player activity both during and after the event
- Classifies games by the health and trajectory of their player base — not just current headcount
- Detects and surfaces unusual player activity changes, associating them with known market events

---

## 3. Primary Downstream Questions

These four questions define what the platform must be capable of answering. All other analytical features support these.

### Q1 — Player Lifecycle
How do games acquire, lose, retain, and recover player activity over their lifecycle?

Enables users to understand: Is this game still growing? Has it stabilised? How quickly did it decline after launch? Has it recovered after a decline? How does it compare with similar games?

*Useful for: developers, publishers, investors, analysts.*

### Q2 — Sale Effect
Does a game's player activity remain elevated after a promotion ends, or return to its previous baseline?

Enables users to understand: How large was the spike? How long did it last? Did the post-sale baseline shift? Do deeper discounts produce stronger or longer-lasting effects? Do older games behave differently?

*Useful for: publishers, pricing and marketing teams.*

### Q3 — Player Base Health
Can we distinguish a game in a stable state from a game in sustained decline, even when their current player counts are similar?

Example:
- Game A: 1,100 → 1,050 → 1,020 → 1,000 (stable)
- Game B: 5,000 → 3,500 → 2,000 → 1,000 (declining)

Both have 1,000 players today. The platform must tell them apart.

*Useful for: publishers, market analysts.*

### Q4 — Market Events & Discovery
Can unusual changes in player activity be detected automatically and associated with known game or market events (sales, patches, DLC, viral moments)?

Enables: anomaly surfacing without manual game selection — the system discovers which games are experiencing unusual activity.

*Useful for: research analysts, publishers.*

---

## 4. Supporting Analytical Questions

- **Q5 — Genre & Game Type Comparison:** Do multiplayer games retain players differently to single-player games? Are some genres more volatile? Do free-to-play games show different patterns to paid titles?
- **Q6 — Weekly Activity Shape:** How does activity vary across the week for different games? (No demographic inferences are made from timestamps alone.)
- **Q7 — Quality & Reception Correlation:** Does a game's critic score or player sentiment (completion rate, drop rate, rating distribution) correlate with long-term player retention?

---

## 5. Target User Personas

### Indie Developer / Studio
"I'm considering entering this market. What do player curves look like for games in this category after launch? Do sales create lasting player activity or just temporary spikes?"

### Publisher / Market Analyst
"Which games are gaining or losing momentum? What happened to player activity after this promotion? Which games are showing sustained decline?"

### Research / Data Analyst
"How do player lifecycle patterns differ between game types? Can we detect unusual activity automatically? Are sales, patches, and events associated with measurable changes?"

---

## 6. Project Scope

### In Scope
- Ingestion of game metadata, pricing history, player activity, and sentiment data from multiple external APIs and local datasets
- Cross-source identity resolution (matching the same game across Steam, ITAD, RAWG, and optionally OpenCritic)
- A PostgreSQL-backed three-layer data warehouse (raw → staging → analytical)
- Scheduled ingestion and pipeline orchestration using the most appropriate mechanism for the workload (currently GitHub Actions; Apache Airflow is being evaluated for multi-source orchestration)
- Staging-to-analytical transforms via dbt Core
- Live player count collection (currently running hourly for the tracked set of ~50 games; 30 with 5-minute granularity history)
- Analytical model supporting all four primary downstream questions
- Dashboard presenting key findings

### Out of Scope
- Console or mobile platform analysis (Steam is PC-only; RAWG console data collected for metadata only)
- Wishlist or demographic data (not exposed via public APIs)
- Regional pricing breakdowns (not available from confirmed sources)
- Real-time streaming (scheduled batch ingestion is sufficient)
- Social media / YouTube / Reddit footprint analysis (scope risk; deferred)
- Franchise / game-series graph analysis (no downstream question maps to this)
- OpenGameStats (rejected: data only from 2026 onward)

---

## 7. Tracked Game Catalogue (~50 Games)

The tracked catalogue comprises ~50 games in two tiers:

- **30 granular games** — confirmed to have 5-minute granularity historical player data in the local CSV dataset. Games were selected to maximise analytical diversity across lifecycle patterns, monetisation models, and genre.
- **~20 newer games** — recent and emerging titles without granular historical data; they remain in the tracked set so live data can accumulate and historical backfill is possible if needed in future.

| App ID | Game | Analytical Role |
|---|---|---|
| 570 | Dota 2 | Massive live-service, ultra-stable long-term baseline |
| 730 | CS2 | Platform migration event (replaced CS:GO) |
| 39210 | Final Fantasy XIV | Legendary recovery from disastrous launch |
| 105600 | Terraria | 10-year lifecycle, highly sale-sensitive |
| 218620 | Payday 2 | Highly sale-driven, very spiky behaviour |
| 221100 | DayZ | Long rocky early access, niche retention |
| 227300 | Euro Truck Simulator 2 | Textbook stable healthy player base |
| 230410 | Warframe | Free-to-play — no price signals, pure engagement |
| 236390 | War Thunder | Free-to-play contrast to paid titles |
| 238960 | Path of Exile | League releases create periodic spikes |
| 251570 | 7 Days to Die | 10-year early access, unique lifecycle shape |
| 252490 | Rust | Well-documented sale spikes and baseline shifts |
| 255710 | Cities: Skylines | Long stable tail, modding community effect |
| 264710 | Subnautica | Early access → 1.0 launch spike clearly visible |
| 275850 | No Man's Sky | Best recovery story in gaming |
| 281990 | Stellaris | Paradox DLC model — expansion-driven spikes |
| 292030 | The Witcher 3 | Mid-life revival driven by Netflix show |
| 294100 | RimWorld | Never on sale — pure word-of-mouth growth |
| 359550 | Rainbow Six Siege | Slow-burn growth years after launch |
| 374320 | Dark Souls III | Classic single-player sale-spike pattern |
| 377160 | Fallout 4 | TV show revival — parallels Witcher 3 |
| 394360 | Hearts of Iron IV | Paradox DLC model — comparison to Stellaris |
| 413150 | Stardew Valley | Indie, sale-sensitive, weekend-heavy pattern |
| 427520 | Factorio | Almost never goes on sale — control case |
| 435150 | Divinity: Original Sin 2 | Strong launch peak, long healthy tail |
| 489830 | Skyrim SE | Multiple re-releases, relaunch spikes visible |
| 578080 | PUBG | Peaked hard, declined fast — clean decay curve |
| 588650 | Dead Cells | Indie roguelike with visible DLC spike pattern |
| 646570 | Slay the Spire | One of the cleanest indie success curves |

All 30 granular games are present in the Part1 5-minute granularity CSV dataset, verified against the local game list.

---

## 8. Data Sources

| Source | Purpose | Access | Status |
|---|---|---|---|
| Steam Store API | Game metadata, current pricing, reviews, Metacritic score | Public, no key | Active |
| IsThereAnyDeal (ITAD) v2 | Historical price data, discount events | Free tier, API key registered | Active |
| RAWG API | Metadata enrichment, ID resolution, sentiment, playtime, completion/drop rates | Free tier, 20k req/month | Active |
| OpenCritic API | Critic scores | Free, no key | Pending empirical test |
| Local 5-min CSVs (Part1) | High-resolution historical concurrent players | Local files | Available — all 30 games confirmed |
| Local hourly CSVs (Part2) | Additional historical concurrent players | Local files | Available |
| Local monthly CSVs | Valve + SteamCharts monthly player counts | Local files | Available |
| Live Steam collection | Current concurrent players, ~50 games, ongoing | Direct API | Running |
| SteamCharts | 2018–present monthly gap-fill | Scraping | Verified (no ToS prohibition) |

---

## 9. Metrics Collected

| Metric | Source | Frequency | Supports | Priority |
|---|---|---|---|---|
| Steam App ID | Steam | Once | All | 🔴 |
| Game name | Steam | Once | All | 🔴 |
| Release date | Steam / RAWG | Once | Q1, Q5 | 🔴 |
| Game type / is_multiplayer | Steam | Once | Q5 | 🔴 |
| Genre | Steam / RAWG | Once | Q5 | 🔴 |
| Concurrent players (live) | Steam | Hourly | Q1, Q2, Q3, Q4 | 🔴 |
| Concurrent players (historical 5-min) | Local CSVs | One-time load | Q1, Q2, Q3, Q4 | 🔴 |
| Current price | Steam / ITAD | Daily | Q2 | 🔴 |
| Original (list) price | Steam / ITAD | Daily | Q2 | 🔴 |
| Discount % | Steam / ITAD | Daily | Q2 | 🔴 |
| Historical price events | ITAD | Once per game | Q2 | 🔴 |
| Positive review count | Steam | Weekly | Q7 | 🟡 |
| Negative review count | Steam | Weekly | Q7 | 🟡 |
| Metacritic score (PC) | Steam `appdetails` | Once | Q7 | 🟡 |
| Metacritic score by platform | RAWG | Once | Q7 | 🟡 |
| RAWG 4-tier rating distribution | RAWG | Once | Q7 | 🟡 |
| Completion / drop rates (`added_by_status`) | RAWG | Once | Q3, Q7 | 🟡 |
| Average playtime (hours) | RAWG | Once | Q5, Q7 | 🟡 |
| Critic score | OpenCritic (if confirmed) | Once | Q7 | 🟡 |
| Steam news / patch events | Steam ISteamNews | On-demand | Q4 | 🟢 |
| Peak players (derived) | Derived from concurrent snapshots | — | Q1 | — |
| Sale period (derived) | Derived from discount % > 0 | — | Q2 | — |
| Pre/post-sale baseline (derived) | Derived from player time series | — | Q2 | — |

---

## 10. Success Criteria

1. Pipeline reliably ingests data from at least three external sources without manual intervention
2. Cross-source ID resolution links all ~50 games across Steam, ITAD, and RAWG correctly
3. Analytical model supports answering Q1, Q2, Q3, and at least one Q4 anomaly detection output is demonstrated end-to-end across all 30 granular games
4. Player lifecycle curves and health classifications are computable for all 30 granular games; newer additions accumulate history via live collection
5. dbt models transform staging data into the analytical layer with documented lineage
6. The recurring pipeline is reliably scheduled and orchestrated end-to-end; the final orchestration implementation is selected based on workload complexity and operational requirements
7. Dashboard presents findings for at least two primary downstream questions visually
8. Pipeline handles API errors, rate limits, and missing data gracefully without halting

---

## 11. Constraints & Assumptions

- **Budget:** Free API tiers and open-source tooling only
- **Database:** PostgreSQL; currently Neon for prototyping; host may change (connection string via env var)
- **Game selection:** Primary analysis tier restricted to games with confirmed 5-minute granularity CSV data — 30 games selected on this basis; ~20 additional newer games tracked via live collection without granular historical data
- **Historical gap:** 2018–present monthly-only from SteamCharts; 5-minute data covers pre-2018; live collection covers present forward
- **Q4 scope:** Anomaly detection flags unusual windows and surfaces nearest Steam news post; fully automated event classification is out of scope
- **SteamDB:** Reference and validation only — not an automated ingestion source
- **OpenCritic:** Integration conditional on empirical test confirming Steam App ID resolution path
