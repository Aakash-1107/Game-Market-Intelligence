# Technical Requirements Document (TRD)
## Game Market Intelligence & Player Activity

**Version:** 1.0
**Date:** September 2026
**Author:** Aakash

---

## 1. System Overview

The platform is a batch data pipeline built around a three-layer storage architecture (raw → staging → analytical). External API responses are persisted as JSONB in the raw layer before transformation, enabling reprocessing without re-calling APIs. The current recurring ingestion is scheduled hourly through GitHub Actions. dbt Core is used for the staging-to-analytical transformation layer. Apache Airflow is evaluated as a possible orchestration layer for coordinating multiple recurring ingestion and transformation tasks; it is not a requirement simply because it is an industry-standard tool.

Live concurrent player data for the tracked set of ~50 games is currently collected hourly from Steam. Of these, 30 games have historical 5-minute granularity player data loaded from local CSV files; the remaining ~20 games are newer additions without granular historical data but remain in the tracked set and can be collected in future if needed. The setup is designed to be deployable via Docker Compose and to scale to the full Steam catalogue of ~184,992 apps without architectural changes.

```
External APIs          Local Datasets
(Steam, ITAD,          (5-min CSVs,
 RAWG, OpenCritic)      SteamCharts)
       │                     │
       └──────────┬──────────┘
                  ▼
        ┌─────────────────────┐
        │   Raw Layer (JSONB) │  ← Python ingestion jobs
        └─────────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │   Staging Layer     │  ← dbt models (typed, cleaned)
        └─────────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │  Analytical Layer   │  ← dbt models (star schema)
        │   (Star Schema)     │
        └─────────────────────┘
                  │
                  ▼
             Dashboard

      Recurring stages are currently scheduled through GitHub Actions; orchestration may move to Apache Airflow if multi-source dependency management, retries, monitoring, or scheduling complexity justifies the additional component
```

---

## 2. Technology Stack

| Component | Technology | Role |
|---|---|---|
| Language | Python 3.x | Ingestion scripts, API calls, CSV loading |
| Database | PostgreSQL (host TBD; Neon for prototyping) | All three storage layers |
| Orchestration | GitHub Actions currently; Apache Airflow evaluated | Hourly scheduling currently handled by GitHub Actions; Airflow may be introduced if orchestration complexity justifies it |
| Transformation | dbt Core (free, open-source) | Staging → analytical layer transforms with lineage and tests |
| Containerisation | Docker Compose (evaluated) | Optional local reproducibility for the ingestion scripts and PostgreSQL; only added if local setup complexity justifies it |
| API interaction | `requests` | All HTTP calls |
| Data manipulation | `pandas` | CSV loading, profiling, Python-side transforms |
| Web scraping | `beautifulsoup4` | SteamCharts |
| DB driver | `psycopg2-binary` | Python → PostgreSQL connection |
| Config management | `python-dotenv` | API keys and DB connection via env vars |
| Dashboard | Metabase or another suitable visualisation tool | Final analytical presentation and dashboard layer; final tool to be selected based on project requirements |

### Technology Selection Rationale

Technology choices are driven by the project's analytical requirements, data volume, update frequency, and operational needs rather than by maximising the number of technologies used.

- **GitHub Actions** — currently provides reliable hourly scheduling for the ~50-game live ingestion and is sufficient for the current workload.
- **dbt** — retained because the project has a clear SQL transformation boundary from raw data to staging and analytical marts. dbt provides versioned models, tests, documentation, and lineage.
- **Apache Airflow** — evaluated rather than assumed. It becomes justified if the pipeline grows into multiple independently scheduled sources and dependent tasks where centralised scheduling, retries, monitoring, and reruns provide material operational value. If those needs do not outweigh the added complexity, GitHub Actions remains the simpler choice.
- **Docker / Docker Compose** — evaluated on its own merits, not coupled to Airflow adoption. If used, it can provide a reproducible local environment for the ingestion scripts and PostgreSQL. It is only introduced if local runner or deployment complexity justifies it, and is not required for the current GitHub Actions + Neon architecture.
- **PostgreSQL** — appropriate for the current dataset size and analytical workload; the star schema demonstrates core data-modelling skills without introducing an unnecessary warehouse platform.

---

## 3. Data Sources — Technical Specification

### 3.1 Steam Store API

- **Endpoints:**
  - `https://store.steampowered.com/api/appdetails?appids={appid}` — metadata, pricing, reviews, Metacritic
  - `https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}` — live concurrent players
  - `https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={appid}` — patch notes and news events
- **Auth:** None required for above endpoints
- **Rate limit:** ~200 requests per 5 minutes (unofficial)
- **Key fields from `appdetails`:** `name`, `steam_appid`, `type`, `developers`, `publishers`, `genres`, `release_date`, `price_overview`, `recommendations`, `metacritic`
- **Ingestion strategy:** Cache-aside — check raw table first, call API on miss, store JSONB with `fetched_at`

### 3.2 IsThereAnyDeal (ITAD) API v2

- **Base URL:** `https://api.isthereanydeal.com`
- **Auth:** API key (registered, query param)
- **Key endpoints:**
  - `/games/prices/v3` — current prices across stores
  - `/games/history/v2` — full historical price records per game
- **Ingestion strategy:** Historical prices fetched once per game; current prices re-fetched daily
- **Why ITAD is non-optional for Q2:** Steam does not expose historical price data. Without ITAD, past sale events for the ~50 tracked games are unknown and the sale-effect analysis cannot be performed on historical periods.
- **Reference:** `https://docs.isthereanydeal.com`

### 3.3 RAWG API

- **Base URL:** `https://api.rawg.io/api`
- **Auth:** API key (query param)
- **Rate limit:** 20,000 requests/month (free tier)
- **Key endpoints and fields collected:**

| Endpoint | Fields used | Purpose |
|---|---|---|
| `/games?search={name}` | `id`, `name` | ID resolution — find RAWG ID from game name |
| `/games/{id}` | `genres`, `tags`, `playtime`, `ratings`, `added_by_status`, `metacritic`, `metacritic_platforms` | Metadata enrichment, sentiment, completion rates |
| `/games/{id}/stores` | Store URLs | Extract Steam App ID via regex for cross-source mapping |

- **RAWG fields and their analytical use:**

| Field | What it is | Analytical use |
|---|---|---|
| `added_by_status.beaten` | Players who completed the game | Completion rate = `beaten / owned` |
| `added_by_status.dropped` | Players who abandoned the game | Drop rate = `dropped / owned` — churn signal for Q3 |
| `added_by_status.playing` | Currently active on RAWG | Engagement snapshot |
| `added_by_status.owned` | Total owners across platforms | Denominator for rates |
| `ratings` | 4-tier distribution (Exceptional / Recommended / Meh / Skip) | Richer sentiment than Steam binary for Q7 |
| `playtime` | Average completion time in hours | Normalisation variable for lifecycle analysis |
| `metacritic_platforms` | Per-platform Metacritic scores | Richer critic data than Steam's single score |

- **Important caveat:** `added_by_status` and `ratings` are RAWG-platform-specific user metrics — they reflect users who catalogued the game on RAWG, not the Steam user base. They are used as *proxy signals*, not Steam-equivalent metrics. This distinction must be documented in the analytical layer.

### 3.4 OpenCritic API *(status: pending empirical test)*

- **Base URL:** `https://api.opencritic.com/api`
- **Auth:** None required
- **Key endpoints:**
  - `/game/search?criteria={name}` — search by name
  - `/game/{id}` — full game detail with critic scores
- **Fields of interest:** `topCriticScore`, `percentRecommended`, `numReviews`, `tier`
- **ID resolution path:** Unconfirmed — must test empirically against Cyberpunk 2077 (`1091500`) before building
- **Fallback:** If OpenCritic Steam ID resolution fails, use Metacritic score from Steam `appdetails` + RAWG `metacritic_platforms`

### 3.5 SteamCharts

- **Access:** Web scraping (`beautifulsoup4`)
- **ToS status:** Reviewed — no prohibition on automated data collection found
- **Purpose:** Fill the 2018–present monthly gap between local CSV data and live collection
- **URL pattern:** `https://steamcharts.com/app/{steam_appid}`
- **Data available:** Monthly average and peak concurrent players per game
- **Rate limiting:** `time.sleep(2)` between requests minimum

### 3.6 Local CSV Datasets

| Dataset | Granularity | Period | Target raw table |
|---|---|---|---|
| `PlayerCountHistoryPart1/` (per-game CSVs) | 5-minute | Pre-2018 | `raw_player_5min` |
| `PlayerCountHistoryPart2/` (per-game CSVs) | Hourly | Varies | `raw_player_hourly` |
| `steamcharts.csv` | Monthly | 2012–2025 | `raw_player_monthly` |
| `Valve_Player_Data.csv` | Monthly | 2012–2021 | `raw_player_monthly` |

> All 30 tracked games are confirmed present in Part1 (5-minute).

---

## 4. Database Architecture

### 4.1 Layer Definitions

| Layer | Tool | Purpose | Modification policy |
|---|---|---|---|
| **Raw** | Python ingestion scripts | Full API responses as JSONB + `fetched_at` | Never modified after insert |
| **Staging** | dbt models | Typed, cleaned, one row per entity per source | Rebuilt on each dbt run |
| **Analytical** | dbt models | Star schema for downstream queries | Rebuilt from staging |

### 4.2 Key Raw Tables

```sql
raw_steam_appdetails (
    steam_appid     INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_steam_player_live (
    steam_appid     INTEGER,
    concurrent_players INTEGER,
    fetched_at      TIMESTAMP
)

raw_steam_news (
    steam_appid     INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_itad_price_history (
    steam_appid     INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_itad_price_current (
    steam_appid     INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_rawg_game (
    rawg_id         INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_opencritic_game (
    oc_id           INTEGER,
    raw_response    JSONB,
    fetched_at      TIMESTAMP
)

raw_player_5min (
    steam_appid     INTEGER,
    recorded_at     TIMESTAMP,
    concurrent_players INTEGER,
    data_source     VARCHAR   -- 'csv_part1'
)

raw_player_hourly (
    steam_appid     INTEGER,
    recorded_at     TIMESTAMP,
    concurrent_players INTEGER,
    data_source     VARCHAR   -- 'csv_part2'
)

raw_player_monthly (
    steam_appid     INTEGER,
    month           DATE,
    avg_players     NUMERIC,
    peak_players    INTEGER,
    data_source     VARCHAR   -- 'csv_steamcharts', 'csv_valve', 'steamcharts_scrape'
)
```

### 4.3 Cross-Source Identity Resolution

```sql
game_source_mapping (
    game_key        INTEGER,
    source          VARCHAR,   -- 'steam', 'rawg', 'itad', 'opencritic'
    source_game_id  VARCHAR
)
```

**Resolution flow:**
1. RAWG search by name → RAWG ID
2. RAWG `/stores` → regex extract Steam App ID → verify match
3. ITAD lookup by Steam App ID (native support)
4. OpenCritic search by name → OC ID (after empirical test)

### 4.4 Analytical Schema (Star Schema)

**Dimension tables** (built by dbt)

| Table | Key fields |
|---|---|
| `dim_game` | `game_key`, `name`, `release_date`, `game_type`, `is_multiplayer`, `is_free_to_play`, `avg_playtime_hours` |
| `dim_genre` | `genre_key`, `genre_name` |
| `dim_developer` | `developer_key`, `developer_name` |
| `dim_date` | `date_key`, `date`, `year`, `month`, `week`, `day_of_week`, `is_weekend`, `is_holiday_period` |
| `dim_source` | `source_key`, `source_name` |

**Fact tables** (built by dbt)

| Table | Grain | Key measures |
|---|---|---|
| `fact_player_activity` | One row per game per timestamp | `concurrent_players`, `data_resolution` (`5min` / `hourly` / `monthly`) |
| `fact_price_snapshot` | One row per game per day | `original_price`, `current_price`, `discount_pct`, `currency`, `is_on_sale` |
| `fact_reviews` | One row per game per snapshot date | `positive_reviews`, `negative_reviews`, `review_score_label` |
| `fact_sentiment` | One row per game (periodic) | `rating_exceptional`, `rating_recommended`, `rating_meh`, `rating_skip`, `completion_rate`, `drop_rate`, `metacritic_score`, `oc_score` |

---

## 5. dbt Model Structure

```
models/
├── staging/
│   ├── stg_steam_games.sql          -- extract fields from raw_steam_appdetails
│   ├── stg_steam_prices.sql         -- extract price_overview fields
│   ├── stg_steam_reviews.sql        -- extract review counts and labels
│   ├── stg_player_activity.sql      -- union 5min + hourly + monthly + live
│   ├── stg_itad_price_history.sql   -- parse price event arrays → one row per event
│   ├── stg_rawg_games.sql           -- extract metadata, sentiment, completion rates
│   └── stg_opencritic.sql           -- extract critic scores
├── intermediate/
│   └── int_price_with_discount.sql  -- compute discount_pct, is_on_sale flag
└── marts/
    ├── dim_game.sql
    ├── dim_genre.sql
    ├── dim_date.sql
    ├── fact_player_activity.sql
    ├── fact_price_snapshot.sql
    ├── fact_reviews.sql
    └── fact_sentiment.sql
```

dbt tests applied:
- `not_null` on all primary keys
- `unique` on all surrogate keys
- `accepted_values` on `data_resolution`, `is_on_sale`
- `relationships` between facts and dimensions

---

## 6. Orchestration Strategy

### 6.1 Current implementation

The recurring live-player ingestion is currently scheduled hourly using GitHub Actions. This is the working production path for the current ~50-game workload:

```
GitHub Actions (hourly)
        │
        ▼
Python ingestion
        │
        ▼
Neon PostgreSQL / raw layer
```

This implementation is intentionally simple and is appropriate while the recurring workload remains small.

### 6.2 Airflow evaluation

Apache Airflow is not required merely because it is an industry-standard tool. It is being evaluated for the point at which the pipeline contains enough independent recurring tasks and dependencies that a dedicated orchestrator provides clear operational value.

A potential Airflow DAG would look like:

```
start
  │
  ├── collect_steam_players
  ├── collect_steam_prices
  ├── collect_itad_prices
  │
  └── [collection tasks complete]
          │
          ▼
      dbt staging
          │
          ▼
       dbt marts
          │
          ▼
       dbt tests
          │
          ▼
    ingestion summary
          │
          ▼
         end
```

If Airflow is adopted, the DAG will be scheduled according to the actual freshness requirements of the data rather than arbitrarily being described as a daily DAG. Player activity can remain hourly while slower-changing sources such as metadata or reviews can have less frequent schedules or separate tasks/DAGs.

### 6.3 Decision criteria

Airflow will be justified if it provides measurable value in one or more of the following areas:

- Multiple recurring ingestion schedules
- Explicit task dependencies between ingestion and dbt transformations
- Centralised retry and failure handling
- Pipeline execution monitoring and historical run visibility
- Selective task reruns without rerunning the entire workflow
- A clearer operational model as the number of sources increases

If these requirements remain adequately handled by GitHub Actions, introducing Airflow would add complexity without sufficient benefit and the project will retain GitHub Actions for scheduling.

### 6.4 One-time data loads

The following operations are bootstrap/backfill tasks and are not expected to execute on every recurring run:

- CSV bootstrap
- Cross-source ID resolution
- ITAD historical price backfill
- SteamCharts historical scrape

These can be executed manually or through dedicated one-off workflows. They do not by themselves justify installing Airflow.

## 7. Ingestion Design

### 7.1 Cache-Aside Pattern

```
Request game data
       │
       ▼
 Check raw table (appid + source + staleness window)
       │
   ┌───┴───┐
  Hit     Miss
   │       │
   ▼       ▼
Return   Call API → Store JSONB + fetched_at
JSONB
```

### 7.2 Staleness Policy

| Data type | Re-fetch frequency |
|---|---|
| Game metadata | Once (manual trigger to refresh) |
| Historical prices (ITAD) | Once per game |
| Current prices | Daily |
| Concurrent players (live) | Daily |
| Review scores | Weekly |
| Sentiment / RAWG data | Once per game (monthly refresh optional) |
| SteamCharts historical | Once per game; most recent month refreshed monthly |

### 7.3 Error Handling

- HTTP 429 → exponential backoff with jitter
- Per-game try/except — one game failing does not halt the batch
- All errors logged to `ingestion_log` with: `game_id`, `source`, `endpoint`, `http_status`, `timestamp`, `error_message`
- Raw layer never modified — transform failures are always recoverable by re-running dbt

---

## 8. Ingestion Log Table

```sql
ingestion_log (
    run_id          UUID DEFAULT gen_random_uuid(),
    run_timestamp   TIMESTAMP DEFAULT NOW(),
    source          VARCHAR,
    stage           VARCHAR,       -- 'raw', 'dbt_staging', 'dbt_marts'
    game_id         VARCHAR,
    status          VARCHAR,       -- 'success', 'failed', 'skipped'
    http_status     INTEGER,
    error_message   TEXT,
    rows_affected   INTEGER
)
```

---

## 9. Tracked Game Coverage

All 30 granular games confirmed in the Part1 5-minute dataset.

| Coverage tier | Count | Notes |
|---|---|---|
| 5-minute historical | 30 | Confirmed in the Part1 dataset |
| Live collection | ~50 | All tracked games, collected hourly |
| Newer games (no granular history) | ~20 | Tracked for live/latest data; granular backfill possible in future |
| Monthly gap (2018–present) | 30 | Filled via SteamCharts scrape for granular-set games |
| ITAD price history | ~50 (expected) | Price records collectible for all tracked games |
| RAWG metadata + sentiment | ~50 (expected) | All major titles should resolve |

---

## 10. Source Decisions & Rationale

| Decision | Rationale |
|---|---|
| Airflow as an evaluated orchestration option | Justified only if multi-source scheduling, dependencies, retries, and monitoring create enough operational complexity to warrant it |
| dbt for transforms | Industry standard transform layer; adds lineage, tests, documentation to SQL |
| Docker Compose | Evaluated for a reproducible local environment; not required while GitHub Actions + Neon suffices |
| JSONB raw storage | Decouple ingestion from schema; reprocess without re-calling APIs |
| PostgreSQL only | Right tool for ~50 games; star schema design demonstrates data modelling |
| Game list restricted to 5-min data | Ensures Q2 and Q4 are fully answerable; avoids mixed-quality analysis tiers |
| ITAD non-optional | Steam does not expose historical prices; ITAD is the only legitimate source |
| RAWG `added_by_status` as proxy | Completion/drop rates not available from Steam; RAWG proxy signals flagged as such in analytical layer |
| No Kafka / Spark / Snowflake | Inappropriate scale; adds complexity with no analytical benefit at ~50 games |
| OpenCritic test-first | ID resolution empirically unconfirmed; must validate before building |
| SteamCharts scraping permitted | ToS reviewed — no prohibition found |

---

## 11. Architecture Decision Principle

The system follows a bottom-up engineering approach:

**Business questions → required data → data freshness → ingestion → transformation → analytical model → serving → operational tooling.**

The project deliberately avoids adding infrastructure solely for résumé value. Each component must have a demonstrable role in reliability, maintainability, analytical correctness, or developer productivity. This is especially relevant for orchestration: GitHub Actions is currently sufficient for the hourly ~50-game ingestion, while Airflow is evaluated as the workload becomes more multi-source and dependency-driven.

## 12. Implementation Plan

The work is sequenced in phases that build on each other. Ordering may shift if data feasibility or analytical modelling reveal different priorities.

| Phase | Milestone |
|---|---|
| 1 | API feasibility testing; sources confirmed |
| 2 | Ingestion foundation; CSV bootstrap |
| 3 | Steam ingestion; RAWG ID resolution |
| 4 | ITAD price history; SteamCharts gap-fill |
| 5 | dbt project setup; staging models for all sources |
| 6 | OpenCritic integration or fallback confirmed |
| 7 | dbt mart models (star schema); dbt tests passing |
| 8 | Q1–Q3 analytics; lifecycle curves; health classification |
| 9 | Q4 anomaly detection; sale-effect analysis |
| 10 | Dashboard |
| 11 | Orchestration approach validated; end-to-end run |
| 12 | Documentation and architecture diagram |
