import os

import duckdb
from dotenv import load_dotenv


load_dotenv()


con = duckdb.connect()

con.execute("INSTALL httpfs;")
con.execute("LOAD httpfs;")

con.execute(f"""
    CREATE SECRET rustfs_secret (
        TYPE S3,
        KEY_ID '{os.environ["RUSTFS_ACCESS_KEY"]}',
        SECRET '{os.environ["RUSTFS_SECRET_KEY"]}',
        ENDPOINT 'localhost:9000',
        USE_SSL false,
        URL_STYLE 'path'
    );
""")

result = con.execute("""
    SELECT *
    FROM read_csv(
        's3://game-market-raw/raw/steam/app_list/steam_app_list.csv'
    )
    LIMIT 5;
""").fetchdf()

print(result)