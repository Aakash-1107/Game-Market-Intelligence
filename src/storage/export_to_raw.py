import os
import io
from datetime import datetime, timezone
import pandas as pd
import boto3
from botocore.client import Config
import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

# --- Config ---
DATABASE_URL = os.getenv("DATABASE_URL")
RUSTFS_ENDPOINT = "http://localhost:9000"
RUSTFS_ACCESS_KEY = os.getenv("RUSTFS_ACCESS_KEY")
RUSTFS_SECRET_KEY = os.getenv("RUSTFS_SECRET_KEY")
BUCKET = "game-market-raw"

# Path convention: raw/steam/player_counts/YYYY/MM/DD/
def make_object_key():
    now = datetime.now(timezone.utc)
    return (
        f"raw/steam/player_counts/"
        f"{now.year}/{now.month:02d}/{now.day:02d}/"
        f"player_counts_{now.strftime('%Y%m%d_%H%M%S')}.parquet"
    )

def fetch_from_neon() -> pd.DataFrame:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        df = pd.read_sql(
            "SELECT id, recorded_at, appid, game_name, player_count FROM steam_player_counts ORDER BY recorded_at",
            conn
        )
        print(f"Fetched {len(df)} rows from Neon.")
        return df
    finally:
        conn.close()

def upload_parquet(df: pd.DataFrame, object_key: str):
    s3 = boto3.client(
        "s3",
        endpoint_url=RUSTFS_ENDPOINT,
        aws_access_key_id=RUSTFS_ACCESS_KEY,
        aws_secret_access_key=RUSTFS_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)

    s3.put_object(
        Bucket=BUCKET,
        Key=object_key,
        Body=buffer.getvalue(),
        ContentType="application/octet-stream",
    )
    print(f"Uploaded to s3://{BUCKET}/{object_key}")
    print(f"Rows: {len(df)} | Size: {buffer.tell():,} bytes")

def main():
    print("Starting Neon → RustFS export...")
    df = fetch_from_neon()

    if df.empty:
        print("No data to export.")
        return

    object_key = make_object_key()
    upload_parquet(df, object_key)
    print("Export complete.")

if __name__ == "__main__":
    main()