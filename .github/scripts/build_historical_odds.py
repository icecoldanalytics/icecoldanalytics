#!/usr/bin/env python3
"""
Piece 3 of 4: builds data/historical_prop_odds.json — real historical
market odds/lines for every game in our props log, pulled from The
Odds API's historical endpoint, snapshotted close to actual game time.
"""
import json
import os
import time
import requests
from datetime import datetime, timedelta

API_KEY = os.environ.get("ODDS_API_KEY", "")
if not API_KEY:
    print("ODDS_API_KEY is not set in this terminal session.")
    raise SystemExit

TEAM_FULL_NAMES = {
    "ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes", "CBJ": "Columbus Blue Jackets", "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche", "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers", "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montréal Canadiens",
    "NJD": "New Jersey Devils", "NSH": "Nashville Predators", "NYI": "New York Islanders",
    "NYR": "New York Rangers", "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins", "SEA": "Seattle Kraken", "SJS": "San Jose Sharks",
    "STL": "St Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets", "WSH": "Washington Capitals"
}

MARKETS = "player_shots_on_goal,player_goal_scorer_anytime,player_points,player_assists"


def get_day_events(date_str):
    """Fetch the day's NHL slate at a time guaranteed to be before any game starts."""
    snapshot = f"{date_str}T15:00:00Z"
    url = f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/events?apiKey={API_KEY}&date={snapshot}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get("data", [])


def get_event_odds(event_id, near_time):
    url = (
        f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/events/{event_id}/odds"
        f"?apiKey={API_KEY}&date={near_time}&regions=us&markets={MARKETS}&oddsFormat=american"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    return r.json()


def main():
    with open("data/player_props_log.json") as f:
        log = json.load(f)

    unique_games = sorted(set((e["date"], e["game"]) for e in log))

    # Resume from existing progress instead of re-fetching everything
    results = {}
    try:
        with open("data/historical_prop_odds.json") as f:
            results = json.load(f)
        print(f"Found existing progress: {len(results)} games already fetched.")
    except FileNotFoundError:
        pass

    remaining = [(d, g) for (d, g) in unique_games if f"{d}|{g}" not in results]
    print(f"Fetching odds for {len(remaining)} remaining games (of {len(unique_games)} total)...")

    misses = []

    for i, (date_str, game) in enumerate(remaining):
        away, home = [t.strip() for t in game.split("@")]
        away_full = TEAM_FULL_NAMES.get(away)
        home_full = TEAM_FULL_NAMES.get(home)

        events = get_day_events(date_str)
        match = None
        for e in events:
            if e["away_team"] == away_full and e["home_team"] == home_full:
                match = e
                break

        if not match:
            misses.append((date_str, game, "no matching event found"))
            continue

        # Pull odds from ~20 min before commence time
        try:
            commence = datetime.strptime(match["commence_time"], "%Y-%m-%dT%H:%M:%SZ")
            near_time = (commence - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            near_time = match["commence_time"]

        odds_data = get_event_odds(match["id"], near_time)
        if odds_data is None:
            misses.append((date_str, game, "odds fetch failed"))
            continue

        results[f"{date_str}|{game}"] = odds_data
        time.sleep(0.3)

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(remaining)} games")

    with open("data/historical_prop_odds.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Successfully pulled: {len(results)}")
    print(f"Missed: {len(misses)}")
    if misses:
        print("\nMissed games:")
        for d, g, reason in misses:
            print(f"  - {d} {g}: {reason}")


if __name__ == "__main__":
    main()
