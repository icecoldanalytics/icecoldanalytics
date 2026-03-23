#!/usr/bin/env python3
"""
Calculates Signal 1, Signal 1 Partial, and Signal 2 performance
for the 2025-26 NHL season and writes data/roi.json.
Runs nightly via GitHub Actions after games finalize.
"""

import os
import json
import requests
from datetime import datetime, timedelta
import pytz

MST = pytz.timezone("America/Edmonton")

NHL_TEAMS = {
    "ANA","ARI","BOS","BUF","CAR","CBJ","CGY","CHI","COL","DAL",
    "DET","EDM","FLA","LAK","MIN","MTL","NJD","NSH","NYI","NYR",
    "OTT","PHI","PIT","SEA","SJS","STL","TBL","TOR","UTA","VAN",
    "VGK","WPG","WSH"
}

SEASON_START = datetime(2025, 10, 1).date()


def get_games_for_date(date_str):
    """Fetch all completed games for a given date."""
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
            if away not in NHL_TEAMS or home not in NHL_TEAMS:
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
        print(f"  Error fetching games for {date_str}: {e}")
        return []


def get_teams_playing_on(date_str):
    """Get set of all teams that played on a given date."""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/score/{date_str}", timeout=10)
        r.raise_for_status()
        data = r.json()
        teams = set()
        for g in data.get("games", []):
            state = g.get("gameState", "")
            if state in ("OFF", "FINAL", "LIVE", "CRIT", "PRE", "FUT"):
                teams.add(g["awayTeam"]["abbrev"])
                teams.add(g["homeTeam"]["abbrev"])
        return teams
    except Exception as e:
        print(f"  Error fetching schedule for {date_str}: {e}")
        return set()


def load_signal2_log():
    """
    Load manually logged Signal 2 games from data/signal2_log.json.
    Format: [{"date": "2026-01-15", "away": "FLA", "home": "NJD"}, ...]
    """
    try:
        with open("data/signal2_log.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  Warning: could not load signal2_log.json: {e}")
        return []


def calc_streak(results):
    """Calculate current win/loss streak from a list of {'fade_won': bool}."""
    if not results:
        return "—"
    streak = 0
    last = results[-1]["fade_won"]
    for r in reversed(results):
        if r["fade_won"] == last:
            streak += 1
        else:
            break
    return f"{streak}{'W' if last else 'L'}"


def calc_monthly_roi(results):
    """Break results into monthly ROI buckets."""
    months = {}
    for r in results:
        month = r["date"][:7]  # "2026-01"
        if month not in months:
            months[month] = {"wins": 0, "losses": 0}
        if r["fade_won"]:
            months[month]["wins"] += 1
        else:
            months[month]["losses"] += 1
    output = []
    for month, data in sorted(months.items()):
        n = data["wins"] + data["losses"]
        profit = data["wins"] * 100 - data["losses"] * 110
        roi = profit / (n * 110) * 100 if n > 0 else 0
        output.append({
            "month": month,
            "wins": data["wins"],
            "losses": data["losses"],
            "roi": round(roi, 1)
        })
    return output


def best_month(monthly):
    """Return label of best ROI month."""
    if not monthly:
        return "—"
    best = max(monthly, key=lambda m: m["roi"])
    dt = datetime.strptime(best["month"], "%Y-%m")
    return dt.strftime("%b %Y")


def main():
    today = datetime.now(MST).date()
    # Don't include today — games may not be final yet
    end_date = today - timedelta(days=1)

    print(f"Calculating ROI from {SEASON_START} to {end_date}...")

    # Build full date range
    dates = []
    d = SEASON_START
    while d <= end_date:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    print(f"Fetching {len(dates)} days of schedule data...")

    # Cache teams playing each day
    teams_by_date = {}
    for i, date_str in enumerate(dates):
        teams_by_date[date_str] = get_teams_playing_on(date_str)
        if i % 30 == 0:
            print(f"  Progress: {date_str}")

    # Load Signal 2 manual log
    sig2_log = load_signal2_log()
    sig2_set = {(e["date"], e["away"], e["home"]) for e in sig2_log}
    print(f"  Signal 2 log: {len(sig2_set)} manually logged games")

    # Evaluate each game
    sig1_results = []
    sig1_partial_results = []
    sig2_results = []
    cancelled = 0

    for date_str in dates:
        games = get_games_for_date(date_str)
        if not games:
            continue

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

            if home in played_prev1:
                home_rest = 1
            elif home in played_prev2:
                home_rest = 2
            else:
                home_rest = 3

            fade_won = g["home_score"] > g["away_score"]

            result = {
                "date": date_str,
                "away": away,
                "home": home,
                "away_score": g["away_score"],
                "home_score": g["home_score"],
                "fade_won": fade_won,
                "home_rest": home_rest
            }

            # Both on B2B — cancel
            if away_b2b and home_b2b:
                cancelled += 1
                continue

            if away_b2b and not home_b2b:
                if home_rest >= 3:
                    sig1_results.append(result)
                    # Check if Signal 2 also fired
                    if (date_str, away, home) in sig2_set:
                        sig2_results.append(result)
                elif home_rest == 2:
                    sig1_partial_results.append(result)

    # ── Calculate stats ──
    def calc_stats(results, odds=-110):
        n = len(results)
        if n == 0:
            return {"games": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "roi": 0.0}
        wins = sum(1 for r in results if r["fade_won"])
        losses = n - wins
        profit = sum(100 if r["fade_won"] else odds for r in results)
        roi = profit / (n * abs(odds)) * 100
        return {
            "games": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / n * 100, 1),
            "roi": round(roi, 1)
        }

    s1 = calc_stats(sig1_results, -110)
    s1p = calc_stats(sig1_partial_results, -110)
    s2 = calc_stats(sig2_results, -108)

    s1_monthly = calc_monthly_roi(sig1_results)
    s1p_monthly = calc_monthly_roi(sig1_partial_results)

    # Last 5 Signal 1 results
    last5 = []
    for r in sig1_results[-5:]:
        last5.append({
            "date": r["date"],
            "away": r["away"],
            "home": r["home"],
            "score": f"{r['away_score']}-{r['home_score']}",
            "fade_won": r["fade_won"]
        })

    output = {
        "generated": datetime.now(MST).strftime("%Y-%m-%d %I:%M %p MT"),
        "season": "2025-26",
        "through_date": end_date.strftime("%Y-%m-%d"),
        "signal1": {
            **s1,
            "avg_odds": -112,
            "streak": calc_streak(sig1_results),
            "best_month": best_month(s1_monthly),
            "monthly": s1_monthly,
            "status": "Active"
        },
        "signal1_partial": {
            **s1p,
            "avg_odds": -110,
            "streak": calc_streak(sig1_partial_results),
            "monthly": s1p_monthly,
            "status": "Active"
        },
        "signal2": {
            **s2,
            "avg_odds": -108,
            "streak": calc_streak(sig2_results),
            "note": "Manually logged — backup goalie confirmed games only",
            "status": "Active"
        },
        "summary": {
            "total_sig1_games": s1["games"],
            "total_partial_games": s1p["games"],
            "total_sig2_games": s2["games"],
            "cancelled_both_b2b": cancelled,
            "last5_sig1": last5
        }
    }

    os.makedirs("data", exist_ok=True)
    with open("data/roi.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ roi.json written")
    print(f"  Signal 1:         {s1['games']} games · {s1['win_rate']}% WR · {s1['roi']:+.1f}% ROI")
    print(f"  Signal 1 Partial: {s1p['games']} games · {s1p['win_rate']}% WR · {s1p['roi']:+.1f}% ROI")
    print(f"  Signal 2:         {s2['games']} games · {s2['win_rate']}% WR · {s2['roi']:+.1f}% ROI")
    print(f"  Cancelled:        {cancelled}")


if __name__ == "__main__":
    main()
