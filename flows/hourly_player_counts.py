import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "First_data_ingest"))
from prefect import flow
import steam_data_ingest

@flow(retries=1, retry_delay_seconds=120)
def steam_player_count_ingest():
    steam_data_ingest.main()