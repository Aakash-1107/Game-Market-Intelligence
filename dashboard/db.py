import os
import sys

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


@st.cache_resource
def get_connection():
    con = duckdb.connect(str(DB_PATH), read_only=True)
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
