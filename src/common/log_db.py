"""Connection for writing ingestion_log (Neon in production; any Postgres works, e.g. a local one).

    conn = connect_log_db()          # never raises
    with conn.cursor() as cur:
        cur.execute("insert into ingestion_log ...", params)
    conn.commit()
    conn.close()

The log is observability, not data: a missing DATABASE_URL, an unreachable database, or a failed insert is reported
as a warning, and the ingestion itself carries on. Without a database the connection is a no-op (reads return
nothing). Not used by the hourly flow (First_data_ingest/steam_data_ingest.py), which has its own guard.
"""
import logging
import os

import psycopg2

log = logging.getLogger(__name__)


def _warn(message: str) -> None:
    log.warning(message)
    print(f"WARNING: {message}")
    try:   # inside a Prefect task, also into the flow run's log
        from prefect import get_run_logger
        get_run_logger().warning(message)
    except Exception:
        pass


class _Cursor:
    def __init__(self, owner: "LogConnection"):
        self._owner = owner
        self._cur = None
        if owner._conn is not None:
            try:
                self._cur = owner._conn.cursor()
            except Exception as e:  # noqa: BLE001
                owner._fail(e)

    def execute(self, *args, **kwargs):
        if self._cur is None:
            return None
        try:
            return self._cur.execute(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self._owner._fail(e)

    def executemany(self, *args, **kwargs):
        if self._cur is None:
            return None
        try:
            return self._cur.executemany(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self._owner._fail(e)

    def fetchall(self) -> list:
        try:
            return self._cur.fetchall() if self._cur is not None else []
        except Exception:  # noqa: BLE001
            return []

    def fetchone(self):
        try:
            return self._cur.fetchone() if self._cur is not None else None
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        try:
            if self._cur is not None:
                self._cur.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


class LogConnection:
    """Wraps a psycopg2 connection (or none). Database errors warn instead of raising."""

    def __init__(self, conn):
        self._conn = conn

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        if self._conn is not None:
            try:
                self._conn.commit()
            except Exception as e:  # noqa: BLE001
                self._fail(e)

    def rollback(self) -> None:
        if self._conn is not None:
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _fail(self, error: Exception) -> None:
        _warn(f"ingestion_log write failed, continuing without it ({type(error).__name__}: {str(error)[:200]})")
        if isinstance(error, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            self.close()            # connection lost: stop trying for the rest of this run
        else:
            self.rollback()         # e.g. a bad row: keep logging the next ones


def connect_log_db(url: str | None = None) -> LogConnection:
    url = url or os.getenv("DATABASE_URL")
    if not url:
        _warn("DATABASE_URL is not set: ingestion_log is not written (the ingestion itself continues)")
        return LogConnection(None)
    try:
        return LogConnection(psycopg2.connect(url, connect_timeout=10))
    except Exception as e:  # noqa: BLE001
        _warn(f"ingestion_log database unreachable ({type(e).__name__}): not written (the ingestion itself continues)")
        return LogConnection(None)
