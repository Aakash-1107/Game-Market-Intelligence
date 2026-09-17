import os
from pathlib import Path

import boto3
from dotenv import load_dotenv


# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables from .env
load_dotenv(PROJECT_ROOT / ".env")


RUSTFS_ENDPOINT = "http://localhost:9000"
BUCKET_NAME = "game-market-raw"

SOURCE_FILE = PROJECT_ROOT / "steam_app_list.csv"
OBJECT_KEY = "raw/steam/app_list/steam_app_list.csv"


def main():
    s3 = boto3.client(
        "s3",
        endpoint_url=RUSTFS_ENDPOINT,
        aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
        region_name="us-east-1",
    )

    print(f"Uploading: {SOURCE_FILE}")
    print(f"Destination: s3://{BUCKET_NAME}/{OBJECT_KEY}")

    s3.upload_file(
        str(SOURCE_FILE),
        BUCKET_NAME,
        OBJECT_KEY,
    )

    print("Upload successful.")


if __name__ == "__main__":
    main()