"""One-off feasibility probe for SteamCharts. Not part of the pipeline."""
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

HEADERS = {"User-Agent": "game-market-capstone/0.1 (student data engineering project)"}
APP_ID = 1091500  # Cyberpunk 2077 - project test game, missing from Kaggle data
TIMEOUT = 30


def probe_robots() -> None:
    r = requests.get("https://steamcharts.com/robots.txt", headers=HEADERS, timeout=TIMEOUT)
    print(f"[robots.txt] status={r.status_code}")
    if r.status_code == 200:
        print(r.text[:500])


def probe_app_page() -> None:
    url = f"https://steamcharts.com/app/{APP_ID}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    print(f"[app page] status={r.status_code} server={r.headers.get('server')} bytes={len(r.text)}")
    if "Just a moment" in r.text or r.status_code in (403, 503):
        print("[app page] Bot-protection challenge detected -> STOP, do not work around it.")
        return
    if r.status_code != 200:
        return
    tables = pd.read_html(StringIO(r.text))
    print(f"[app page] {len(tables)} table(s) found in static HTML")
    for i, t in enumerate(tables):
        print(f"--- table {i}: shape={t.shape}, columns={list(t.columns)}")
        print(t.head(3).to_string())
        print(t.tail(3).to_string())


def probe_chart_json() -> None:
    url = f"https://steamcharts.com/app/{APP_ID}/chart-data.json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    ctype = r.headers.get("content-type", "")
    print(f"[chart-data.json] status={r.status_code} content-type={ctype}")
    if r.status_code != 200 or "json" not in ctype:
        return
    data = r.json()
    print(f"[chart-data.json] points={len(data)}")
    if data and isinstance(data[0], list) and len(data[0]) == 2:
        for label, point in (("first", data[0]), ("last", data[-1])):
            ts = datetime.fromtimestamp(point[0] / 1000, tz=timezone.utc)
            print(f"  {label}: {ts.isoformat()} -> {point[1]}")
        if len(data) > 1:
            step_h = (data[1][0] - data[0][0]) / 1000 / 3600
            print(f"  spacing between first two points: {step_h:.2f} h")
    else:
        print(f"  unexpected structure, first item: {data[:1]}")


if __name__ == "__main__":
    probe_robots()
    probe_app_page()
    probe_chart_json()