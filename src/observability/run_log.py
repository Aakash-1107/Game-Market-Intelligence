"""Stage-level run history and dbt results for the daily flow, written to Neon.

    with log_stage(run_id, "daily_market_refresh", "ingest_prices", records_in=55) as stage:
        result = do_work()
        stage.records_out = result["success"]
    log_skipped(run_id, "daily_market_refresh", "dbt_build", "upstream failed: ingest_prices")
    record_dbt_results(run_id, Path("game_market/target/run_results.json"), not_before=build_started)

Tables: sql/ddl/observability.sql (pipeline_run_log, dbt_node_result). All writes are upserts on the primary key,
so rerunning the logger never duplicates rows.

Observability must never break the pipeline: every database call here is wrapped. A logging failure is reported as
a Python `logging` warning and a Prefect log line (when running inside a flow), and the observed work carries on.
log_stage re-raises the stage's own exception unchanged.

    python -m src.observability.run_log --create    # create the tables in Neon (idempotent)
"""
import json
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
DDL = ROOT / "sql" / "ddl" / "observability.sql"
log = logging.getLogger(__name__)


def _warn(message: str) -> None:
    """Report a logging problem without raising: Python logging, plus the Prefect run log when there is one."""
    log.warning(message)
    try:
        from prefect import get_run_logger
        get_run_logger().warning(message)
    except Exception:   # outside a flow/task run there is no Prefect logger
        pass


def _execute(sql: str, params=None, many: bool = False) -> bool:
    """Run one statement in its own connection. Returns False (and warns) instead of raising."""
    try:
        with psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10) as conn, conn.cursor() as cur:
            if many:
                cur.executemany(sql, params)
            else:
                cur.execute(sql, params)
        return True
    except Exception as e:   # noqa: BLE001 - observability must never break the pipeline
        _warn(f"observability: write to Neon failed ({type(e).__name__}: {str(e)[:300]})")
        return False


UPSERT_STAGE = """
insert into pipeline_run_log (run_id, flow_name, stage, status, started_at, finished_at,
                              records_in, records_out, error_message)
values (%(run_id)s, %(flow_name)s, %(stage)s, %(status)s, %(started_at)s, %(finished_at)s,
        %(records_in)s, %(records_out)s, %(error_message)s)
on conflict (run_id, stage) do update set
    flow_name = excluded.flow_name, status = excluded.status, started_at = excluded.started_at,
    finished_at = excluded.finished_at, records_in = excluded.records_in, records_out = excluded.records_out,
    error_message = excluded.error_message
"""


@dataclass
class Stage:
    run_id: str
    flow_name: str
    stage: str
    started_at: datetime
    records_in: int | None = None
    records_out: int | None = None

    def _write(self, status: str, finished_at: datetime | None = None, error_message: str | None = None) -> None:
        _execute(UPSERT_STAGE, {
            "run_id": self.run_id, "flow_name": self.flow_name, "stage": self.stage, "status": status,
            "started_at": self.started_at, "finished_at": finished_at, "records_in": self.records_in,
            "records_out": self.records_out, "error_message": error_message,
        })


@contextmanager
def log_stage(run_id: str, flow_name: str, stage: str, records_in: int | None = None):
    """Write `running` on entry, then `success` or `failed` (with finished_at, counts, error). Re-raises the
    stage's exception unchanged; a failure to log never raises."""
    s = Stage(run_id, flow_name, stage, datetime.now(timezone.utc), records_in)
    s._write("running")
    try:
        yield s
    except BaseException as e:
        s._write("failed", datetime.now(timezone.utc), f"{type(e).__name__}: {e}"[:4000])
        raise
    s._write("success", datetime.now(timezone.utc))


def log_skipped(run_id: str, flow_name: str, stage: str, reason: str) -> None:
    now = datetime.now(timezone.utc)
    Stage(run_id, flow_name, stage, now)._write("skipped", now, reason[:4000])


UPSERT_NODE = """
insert into dbt_node_result (run_id, invocation_id, unique_id, resource_type, status, execution_time_s,
                             rows_affected, failures, message, generated_at)
values (%(run_id)s, %(invocation_id)s, %(unique_id)s, %(resource_type)s, %(status)s, %(execution_time_s)s,
        %(rows_affected)s, %(failures)s, %(message)s, %(generated_at)s)
on conflict (invocation_id, unique_id) do update set
    run_id = excluded.run_id, resource_type = excluded.resource_type, status = excluded.status,
    execution_time_s = excluded.execution_time_s, rows_affected = excluded.rows_affected,
    failures = excluded.failures, message = excluded.message, generated_at = excluded.generated_at
"""


def parse_run_results(path: Path, run_id: str) -> tuple[list[dict], dict]:
    """Rows for dbt_node_result, from the fields that exist in run_results.json (dbt 1.12, schema v6):
    metadata.invocation_id, metadata.generated_at, and per result: unique_id, status, execution_time,
    failures, message, adapter_response.rows_affected. resource_type = the unique_id prefix."""
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    rows = [{
        "run_id": run_id,
        "invocation_id": meta["invocation_id"],
        "unique_id": r["unique_id"],
        "resource_type": r["unique_id"].split(".", 1)[0],
        "status": r["status"],
        "execution_time_s": r.get("execution_time"),
        "rows_affected": (r.get("adapter_response") or {}).get("rows_affected"),
        "failures": r.get("failures"),
        "message": r.get("message"),
        "generated_at": meta["generated_at"],
    } for r in data["results"]]
    return rows, meta


def record_dbt_results(run_id: str, path: Path, not_before: datetime | None = None) -> int:
    """Upsert every node of one dbt invocation. Skips (with a warning) a missing file, or a file written before
    `not_before` (dbt crashed before writing results, so the file is from an earlier build). Returns rows written."""
    try:
        rows, meta = parse_run_results(path, run_id)
        started = datetime.fromisoformat(meta.get("invocation_started_at", meta["generated_at"]).replace("Z", "+00:00"))
        if not_before and started < not_before:
            _warn(f"observability: {path.name} is from an earlier dbt invocation ({started:%Y-%m-%d %H:%M:%S} UTC); "
                  "not recorded")
            return 0
    except Exception as e:   # noqa: BLE001
        _warn(f"observability: could not read {path} ({type(e).__name__}: {e})")
        return 0
    return len(rows) if _execute(UPSERT_NODE, rows, many=True) else 0


def create_tables() -> bool:
    return _execute(DDL.read_text(encoding="utf-8"))


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO)
    if "--create" in sys.argv:
        print("tables created" if create_tables() else "FAILED (see warning)")
