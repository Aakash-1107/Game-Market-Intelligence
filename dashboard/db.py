import duckdb
import pandas as pd
from pathlib import Path
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "game_market.duckdb"


@st.cache_resource
def get_connection():
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(show_spinner=False)
def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Run a read-only query against the mart layer. One cursor per call (thread-safe)."""
    cur = get_connection().cursor()
    try:
        return cur.execute(sql, list(params) if params else None).fetchdf()
    finally:
        cur.close()
