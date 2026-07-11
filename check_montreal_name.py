#!/usr/bin/env python3
import os
import requests

API_KEY = os.environ.get("ODDS_API_KEY", "")
if not API_KEY:
    print("ODDS_API_KEY is not set in this terminal session.")
    raise SystemExit

url = f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/events?apiKey={API_KEY}&date=2026-03-15T15:00:00Z"
r = requests.get(url, timeout=15)
print("Status:", r.status_code)
events = r.json().get("data", [])
for e in events:
    if "ontreal" in e["home_team"] or "ontreal" in e["away_team"] or "ANA" in e.get("away_team", ""):
        print(repr(e["away_team"]), "@", repr(e["home_team"]))
print("\nAll teams seen today, for reference:")
for e in events:
    print(" -", repr(e["away_team"]), "@", repr(e["home_team"]))
