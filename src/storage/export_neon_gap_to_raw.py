import os
import io
import boto3
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

# One-time export to recover the Sept 17 21:00 – Sept 19 20:00 data gap.
# Neon table: steam_player_counts
# Destination: raw/steam/player_counts/2026/09/19/player_counts_gap_recovery.parquet
# Do not run again — Prefect writes directly to RustFS from Sept 20 onward.

DB_URL            = os.getenv("DATABASE_URL")
RUSTFS_ENDPOINT   = os.getenv("RUSTFS_ENDPOINT")
RUSTFS_ACCESS_KEY = os.getenv("RUSTFS_ACCESS_KEY")
RUSTFS_SECRET_KEY = os.getenv("RUSTFS_SECRET_KEY")
RUSTFS_BUCKET     = os.getenv("RUSTFS_BUCKET", "game-market-raw")

EXPORT_FROM = "2026-09-19 00:00:00+00"
RUSTFS_KEY  = "raw/steam/player_counts/2026/09/19/player_counts_gap_recovery.parquet"

# ── Extract ───────────────────────────────────────────────────────────────────

def extract_from_neon() -> pd.DataFrame:
    query = text("""
        SELECT
            appid,
            game_name,
            player_count,
            recorded_at
        FROM steam_player_counts
        WHERE recorded_at >= :export_from
        ORDER BY recorded_at ASC
    """)

    print("Connecting to Neon...")
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"export_from": EXPORT_FROM})

    print(f"Extracted {len(df):,} rows (from {EXPORT_FROM})")
    return df

# ── Validate ──────────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("No rows returned — check EXPORT_FROM or table name")

    null_counts = df[["appid", "player_count", "recorded_at"]].isnull().sum()
    if null_counts.any():
        print(f"WARNING: nulls detected:\n{null_counts[null_counts > 0]}")

    print(f"Date range       : {df['recorded_at'].min()} → {df['recorded_at'].max()}")
    print(f"Unique games     : {df['appid'].nunique()}")
    print(f"Unique timestamps: {df['recorded_at'].nunique()}")

# ── Upload ────────────────────────────────────────────────────────────────────

def upload_to_rustfs(df: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)

    s3 = boto3.client(
        "s3",
        endpoint_url=RUSTFS_ENDPOINT,
        aws_access_key_id=RUSTFS_ACCESS_KEY,
        aws_secret_access_key=RUSTFS_SECRET_KEY,
    )

    print(f"Uploading to s3://{RUSTFS_BUCKET}/{RUSTFS_KEY} ...")
    s3.put_object(
        Bucket=RUSTFS_BUCKET,
        Key=RUSTFS_KEY,
        Body=buffer.getvalue(),
    )
    print("Upload complete.")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    df = extract_from_neon()
    validate(df)
    upload_to_rustfs(df)
    print(f"Done. {len(df):,} rows written to {RUSTFS_KEY}")

if __name__ == "__main__":
    main()