import duckdb
import os
from dotenv import load_dotenv

load_dotenv(override=True)

access_key = os.getenv('RUSTFS_ACCESS_KEY')
secret_key = os.getenv('RUSTFS_SECRET_KEY')

print(f"Access key loaded: {'YES' if access_key else 'NO'}")
print(f"Secret key loaded: {'YES' if secret_key else 'NO'}")

con = duckdb.connect()

print("Loading httpfs...")
con.execute("INSTALL httpfs;")
con.execute("LOAD httpfs;")
print("httpfs loaded")

con.execute("SET s3_endpoint='localhost:9000';")
con.execute(f"SET s3_access_key_id='{access_key}';")
con.execute(f"SET s3_secret_access_key='{secret_key}';")
con.execute("SET s3_use_ssl=false;")
con.execute("SET s3_url_style='path';")
print("S3 settings applied")

print("Running query...")
result = con.execute("""
    SELECT *
    FROM read_csv_auto('s3://game-market-raw/raw/steam/app_list/steam_app_list.csv')
    LIMIT 5
""").fetchall()

print(result)