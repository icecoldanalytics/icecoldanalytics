#!/usr/bin/env python3
"""
One-time script to calculate Signal 1 historical performance for the 2025-26 NHL season.
Fetches every game from Oct 1 2025 to today, checks signal conditions, calculates ROI.
"""

import requests
from datetime import datetime, timedelta
import pytz

MST = pytz.timezone("America/Edmonton")

def get_games_for_date(date_str):
    """Fetch all completed games for a given date"""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/score/{date_str}", timeout=10)
        r.raise_for_status()
        data = r.json()
        games = []
        for g in data.get("games", []):
            if g.get("gameState") not in ("OFF", "FINAL"):
                continue
       away = g["awayTeam"]["abbrev"]
            home = g["homeTeam"]["abbrev"]
            # Skip non-NHL teams (Olympics, international)
            nhl_teams = {"ANA","ARI","BOS","BUF","CAR","CBJ","CGY","CHI","COL","DAL",
                         "DET","EDM","FLA","LAK","MIN","MTL","NJD","NSH","NYI","NYR",
                         "OTT","PHI","PIT","SEA","SJS","STL","TBL","TOR","UTA","VAN",
                         "VGK","WPG","WSH"}
            if away not in nhl_teams or home not in nhl_teams:
                continue
            games.append({
                "away": away,
                "home": home,
                "away_score": g["awayTeam"].get("score", 0),
                "home_score": g["homeTeam"].get("score", 0),
                "date": date_str
            })
        return games
    except Exception as e:
        return []

def get_teams_playing_on(date_str):
    """Get set of teams that played on a given date"""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/score/{date_str}", timeout=10)
        r.raise_for_status()
        data = r.json()
        teams = set()
        for g in data.get("games", []):
            if g.get("gameState") in ("OFF", "FINAL", "LIVE", "CRIT", "PRE", "FUT"):
                teams.add(g["awayTeam"]["abbrev"])
                teams.add(g["homeTeam"]["abbrev"])
        return teams
    except:
        return set()

def main():
    today = datetime.now(MST).date()
    start = datetime(2025, 10, 1).date()
    
    print(f"Calculating Signal 1 stats from {start} to {today}")
    print("This may take a few minutes...\n")

    # Build date range
    dates = []
    d = start
    while d <= today:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    print(f"Fetching {len(dates)} days of data...")

    # Cache teams playing each day
    teams_by_date = {}
    for i, date_str in enumerate(dates):
        teams_by_date[date_str] = get_teams_playing_on(date_str)
        if i % 20 == 0:
            print(f"  Fetched schedule for {date_str}...")

    # Now check each game for signal conditions
    sig1_results = []
    sig1_partial_results = []
    cancelled = 0
    no_signal = 0

    for i, date_str in enumerate(dates):
        games = get_games_for_date(date_str)
        if not games:
            continue

        # Get previous days
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        prev1 = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        prev2 = (d - timedelta(days=2)).strftime("%Y-%m-%d")
        prev3 = (d - timedelta(days=3)).strftime("%Y-%m-%d")

        played_prev1 = teams_by_date.get(prev1, set())
        played_prev2 = teams_by_date.get(prev2, set())
        played_prev3 = teams_by_date.get(prev3, set())

        for g in games:
            away = g["away"]
            home = g["home"]

            away_b2b = away in played_prev1
            home_b2b = home in played_prev1

            # Home rest days
            if home in played_prev1:
                home_rest = 1
            elif home in played_prev2:
                home_rest = 2
            else:
                home_rest = 3

            # Signal conditions
            if away_b2b and home_b2b:
                cancelled += 1
                continue

            if away_b2b and not home_b2b and home_rest >= 3:
                # Signal 1 HIGH
                home_won = g["home_score"] > g["away_score"]
                sig1_results.append({
                    "date": date_str,
                    "away": away,
                    "home": home,
                    "away_score": g["away_score"],
                    "home_score": g["home_score"],
                    "fade_won": home_won,
                    "home_rest": home_rest
                })
            elif away_b2b and not home_b2b and home_rest == 2:
                # Signal 1 PARTIAL
                home_won = g["home_score"] > g["away_score"]
                sig1_partial_results.append({
                    "date": date_str,
                    "away": away,
                    "home": home,
                    "away_score": g["away_score"],
                    "home_score": g["home_score"],
                    "fade_won": home_won
                })
            else:
                no_signal += 1

    # Calculate Signal 1 stats
    n1 = len(sig1_results)
    wins1 = sum(1 for r in sig1_results if r["fade_won"])
    losses1 = n1 - wins1
    win_rate1 = wins1 / n1 * 100 if n1 > 0 else 0
    # ROI assuming -110 odds (bet 110 to win 100)
    profit1 = sum(100 if r["fade_won"] else -110 for r in sig1_results)
    roi1 = profit1 / (n1 * 110) * 100 if n1 > 0 else 0

    # Calculate Signal 1 Partial stats
    n1p = len(sig1_partial_results)
    wins1p = sum(1 for r in sig1_partial_results if r["fade_won"])
    win_rate1p = wins1p / n1p * 100 if n1p > 0 else 0
    profit1p = sum(100 if r["fade_won"] else -110 for r in sig1_partial_results)
    roi1p = profit1p / (n1p * 110) * 100 if n1p > 0 else 0

    print("\n" + "="*50)
    print("SIGNAL 1 — FATIGUE EDGE (Away B2B + Home 3+ Days Rest)")
    print("="*50)
    print(f"Games tracked:  {n1}")
    print(f"Wins:           {wins1}")
    print(f"Losses:         {losses1}")
    print(f"Win Rate:       {win_rate1:.1f}%")
    print(f"ROI (@-110):    {roi1:+.1f}%")

    print("\n" + "="*50)
    print("SIGNAL 1 PARTIAL (Away B2B + Home 2 Days Rest)")
    print("="*50)
    print(f"Games tracked:  {n1p}")
    print(f"Wins:           {wins1p}")
    print(f"Losses:         {n1p - wins1p}")
    print(f"Win Rate:       {win_rate1p:.1f}%")
    print(f"ROI (@-110):    {roi1p:+.1f}%")

    print("\n" + "="*50)
    print("OVERALL SUMMARY")
    print("="*50)
    print(f"Total signal games (S1):     {n1}")
    print(f"Total partial games (S1P):   {n1p}")
    print(f"Cancelled (both B2B):        {cancelled}")
    print(f"No signal:                   {no_signal}")

    print("\n--- LAST 10 SIGNAL 1 RESULTS ---")
    for r in sig1_results[-10:]:
        result = "WIN ✅" if r["fade_won"] else "LOSS ❌"
        print(f"  {r['date']} · {r['away']} @ {r['home']} · {r['away_score']}-{r['home_score']} · Fade {r['away']} · {result}")

if __name__ == "__main__":
    main()
