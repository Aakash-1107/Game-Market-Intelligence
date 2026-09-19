import os
import duckdb
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DB_PATH = PROJECT_ROOT / "data" / "game_market.duckdb"


def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Return a persistent DuckDB connection configured for RustFS.
    
    Creates the database file if it doesn't exist yet.
    The S3 settings tell DuckDB how to reach RustFS — it looks like
    AWS S3 to DuckDB because RustFS speaks the same protocol.
    """
    # Create the data/ directory if it doesn't exist
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(DB_PATH))

    # Install and load the httpfs extension — this is what allows
    # DuckDB to read from S3-compatible storage like RustFS
    conn.execute("INSTALL httpfs;")
    conn.execute("LOAD httpfs;")

    # Configure S3 settings to point at local RustFS instead of AWS
    conn.execute(f"""
        SET s3_endpoint='localhost:9000';
        SET s3_access_key_id='{os.getenv("RUSTFS_ACCESS_KEY")}';
        SET s3_secret_access_key='{os.getenv("RUSTFS_SECRET_KEY")}';
        SET s3_use_ssl=false;
        SET s3_url_style='path';
    """)

    return conn


if __name__ == "__main__":
    conn = get_connection()
    
    result = conn.execute("""
        SELECT
            COUNT(*)          AS rows,
            COUNT(DISTINCT appid) AS games,
            MIN(recorded_at)  AS earliest,
            MAX(recorded_at)  AS latest
        FROM read_parquet('s3://game-market-raw/raw/steam/player_counts/**/*.parquet')
    """).fetchone()

    print(f"Persistent DuckDB connected at: {DB_PATH}")
    print(f"Rows: {result[0]}, Games: {result[1]}, From: {result[2]}, To: {result[3]}")
    
    conn.close()