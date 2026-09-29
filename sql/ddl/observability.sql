-- Observability tables (Neon). Written by src/observability/run_log.py from the daily flow
-- (flows/daily_market_refresh.py); read by dbt through a read-only DuckDB attach (source `ops`).
-- Writes are upserts on the primary key, so rerunning the logger never duplicates rows.
--
-- Set up:  psql "$DATABASE_URL" -f sql/ddl/observability.sql   (or python -m src.observability.run_log --create)

-- One row per flow run per stage.
create table if not exists pipeline_run_log (
    run_id          text        not null,   -- Prefect flow run id
    flow_name       text        not null,
    stage           text        not null,   -- resolve_ids, ingest_prices, ingest_app_details, ingest_reviews,
                                            -- ingest_steamcharts, freshness_check, dbt_build
    status          text        not null check (status in ('running', 'success', 'failed', 'skipped')),
    started_at      timestamptz not null,
    finished_at     timestamptz,
    records_in      integer,               -- e.g. games attempted
    records_out     integer,               -- e.g. games succeeded / files written
    error_message   text,
    primary key (run_id, stage)
);

-- One row per dbt node per dbt invocation, parsed from game_market/target/run_results.json.
create table if not exists dbt_node_result (
    run_id            text             not null,  -- Prefect flow run id of the build
    invocation_id     text             not null,  -- run_results.json metadata.invocation_id
    unique_id         text             not null,  -- results[].unique_id
    resource_type     text             not null,  -- model / test / seed (from unique_id prefix)
    status            text             not null,  -- results[].status: success / error / pass / fail / warn / skipped
    execution_time_s  double precision,           -- results[].execution_time
    rows_affected     integer,                    -- results[].adapter_response.rows_affected (null when absent)
    failures          integer,                    -- results[].failures (tests)
    message           text,                       -- results[].message
    generated_at      timestamptz      not null,  -- run_results.json metadata.generated_at
    primary key (invocation_id, unique_id)
);
