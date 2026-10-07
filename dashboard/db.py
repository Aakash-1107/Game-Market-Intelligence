import os
import sys
import urllib.request

import duckdb
import pandas as pd
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.common.duckdb_path import duckdb_path  # noqa: E402

# the file dbt builds: DUCKDB_PATH (relative paths resolved from game_market/, like dbt) or data/game_market.duckdb
DB_PATH = duckdb_path()
# Public snapshot mode (hosted dashboard): when DB_PATH does not exist, the snapshot built by
# src/utils/build_snapshot.py is downloaded once from SNAPSHOT_URL (environment variable or Streamlit secret; http(s)
# or file://) to this path and opened instead.
SNAPSHOT_PATH = ROOT / "data" / "game_market_snapshot.duckdb"


def _snapshot_url() -> str | None:
    if os.getenv("SNAPSHOT_URL"):
        return os.getenv("SNAPSHOT_URL")
    try:
        return st.secrets.get("SNAPSHOT_URL")
    except Exception:  # noqa: BLE001 - no secrets file at all
        return None


@st.cache_resource(show_spinner=False)
def _download_snapshot(url: str) -> Path:
    """Once per container: download to a temporary name, then rename, so a broken download never looks complete."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_name(SNAPSHOT_PATH.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as f:
        while chunk := response.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, SNAPSHOT_PATH)
    return SNAPSHOT_PATH


def database_path() -> Path:
    if DB_PATH.exists():
        return DB_PATH
    if not SNAPSHOT_PATH.exists():
        url = _snapshot_url()
        if not url:
            st.error(f"No database found at {DB_PATH} and no SNAPSHOT_URL is set. Build the warehouse with dbt, or "
                     "set SNAPSHOT_URL to the published snapshot.", icon=":material/database_off:")
            st.stop()
        with st.spinner("Downloading the data snapshot (only on the first visit after a restart)..."):
            _download_snapshot(url)
    return SNAPSHOT_PATH


@st.cache_resource
def _connect(path: str):
    con = duckdb.connect(path, read_only=True)
    if _has_table(con, "meta", "snapshot_info"):
        return con   # the public snapshot has no observability views to attach the logs for
    # The observability views (observability.mart_pipeline_health, staging.stg_ops__*) read Neon live through the
    # same read-only attach dbt uses (alias `ops`). Without DATABASE_URL every other page still works.
    url = os.getenv("DATABASE_URL")
    if url:
        try:
            con.execute("load postgres")
            con.execute("attach '" + url.replace("'", "''") + "' as ops (type postgres, read_only)")
        except Exception as e:  # noqa: BLE001 - the rest of the dashboard must not depend on Neon
            st.session_state["ops_attach_error"] = type(e).__name__
    return con


def _has_table(con, schema: str, table: str) -> bool:
    cur = con.cursor()   # one cursor per call, like _run (the connection is shared across sessions)
    try:
        return cur.execute("select count(*) from duckdb_tables() where schema_name = ? and table_name = ?",
                           [schema, table]).fetchone()[0] == 1
    finally:
        cur.close()


def get_connection():
    return _connect(str(database_path()))


def is_snapshot() -> bool:
    """True when the dashboard reads the public snapshot (src/utils/build_snapshot.py) instead of the full warehouse."""
    return _has_table(get_connection(), "meta", "snapshot_info")


def ops_attached() -> bool:
    try:
        return get_connection().execute(
            "select count(*) from duckdb_databases() where database_name = 'ops'").fetchone()[0] == 1
    except Exception:  # noqa: BLE001
        return False


def _run(sql: str, params: tuple | None) -> pd.DataFrame:
    cur = get_connection().cursor()
    try:
        return cur.execute(sql, list(params) if params else None).fetchdf()
    finally:
        cur.close()


@st.cache_data(show_spinner=False)
def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Run a read-only query against the mart layer. One cursor per call (thread-safe)."""
    return _run(sql, params)


@st.cache_data(show_spinner=False, ttl=60)
def query_live(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Like query(), but cached for 60 s only: for views computed at read time (pipeline health)."""
    return _run(sql, params)
