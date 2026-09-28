-- ingestion_log: run-level data observability. One row per game per ingestion stage per run
-- (plus one pipeline-level row when a run fails before any game is processed).
-- Matches the live Neon table as of 2026-09-28 (no constraints, no indexes).
--
-- Written by every ingestion script (src/ingestion/*.py, First_data_ingest/steam_data_ingest.py).
-- status values in use: success, failed, error, skipped, not_found, no_coverage, matched_auto, matched_manual, matched_imported,
--                       plus historical values (ambiguous, matched, failure) from one-off setup scripts.
--
-- Set up a fresh Postgres:  psql "$DATABASE_URL" -f sql/ddl/ingestion_log.sql

create extension if not exists pgcrypto;   -- gen_random_uuid() (built in from Postgres 13; harmless there)

create table if not exists ingestion_log (
    run_id          uuid         default gen_random_uuid(),
    run_timestamp   timestamptz  default now(),
    source          varchar,       -- e.g. steam, steam_reviews, itad, opencritic, steamcharts
    stage           varchar,       -- e.g. raw, fetch_reviews, resolve_id, price_history
    game_id         varchar,       -- Steam App ID as text; NULL for pipeline-level rows
    status          varchar,
    http_status     integer,
    error_message   text,
    rows_affected   integer
);
