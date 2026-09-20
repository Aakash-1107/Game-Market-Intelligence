# src/storage/migrate_rustfs_to_s3.py
# One-time migration of existing Parquet files from local RustFS to AWS S3.
# Do not run again after migration is complete.

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

# ── Source — local RustFS ─────────────────────────────────────────────────────

rustfs_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("RUSTFS_ENDPOINT"),
    aws_access_key_id=os.getenv("RUSTFS_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("RUSTFS_SECRET_KEY"),
)

# ── Destination — AWS S3 ──────────────────────────────────────────────────────

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),
    region_name=os.getenv("AWS_REGION", "eu-central-1"),
)

RUSTFS_BUCKET = os.getenv("RUSTFS_BUCKET", "game-market-raw")
AWS_BUCKET    = os.getenv("AWS_BUCKET", "game-market-raw")

# Files to migrate
FILES = [
    "raw/steam/player_counts/2026/09/18/player_counts_20260918_094448.parquet",
    "raw/steam/player_counts/2026/09/19/player_counts_gap_recovery.parquet",
]

def migrate():
    for key in FILES:
        print(f"Migrating {key} ...")

        # Download from RustFS into memory
        response = rustfs_client.get_object(Bucket=RUSTFS_BUCKET, Key=key)
        data = response["Body"].read()

        # Upload to S3
        s3_client.put_object(Bucket=AWS_BUCKET, Key=key, Body=data)
        print(f"  Done — {len(data):,} bytes uploaded to s3://{AWS_BUCKET}/{key}")

    print("\nMigration complete.")

if __name__ == "__main__":
    migrate()