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


def load_goalie_history():
    """
    Load the goalie starts cache built by backtest_signal2_history.py.
    Used to determine, for each Signal 1 game, whether the away team
    started their #1 goalie (new Signal 2 definition) — judged only on
    starts accumulated BEFORE that date.
    """
    try:
        with open("data/goalie_starts_cache.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  Warning: could not load goalie_starts_cache.json: {e}")
        return {}


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

    # Load goalie start history and build chronological starts tracker
    goalie_cache = load_goalie_history()
    goalie_games = sorted(goalie_cache.values(), key=lambda g: g["date"])
    print(f"  Goalie history: {len(goalie_games)} games with starter data")

    # Pre-compute, for each (date, away, home): did away start their #1?
    # Walk chronologically so every call uses only prior information.
    MIN_TEAM_GAMES = 10
    starts_tracker = {}
    team_gp = {}
    started_number_one = {}  # (date, away, home) -> True/False/None(unknown)
    for g in goalie_games:
        key = (g["date"], g["away"], g["home"])
        starter = g.get("away_starter", "")
        t_starts = starts_tracker.get(g["away"], {})
        gp = team_gp.get(g["away"], 0)
        if starter and gp >= MIN_TEAM_GAMES and t_starts:
            leader = max(t_starts.values())
            started_number_one[key] = t_starts.get(starter, 0) >= leader
        else:
            started_number_one[key] = None  # not enough info yet
        for team, s in ((g["away"], g.get("away_starter")), (g["home"], g.get("home_starter"))):
            team_gp[team] = team_gp.get(team, 0) + 1
            if s:
                starts_tracker.setdefault(team, {})
                starts_tracker[team][s] = starts_tracker[team].get(s, 0) + 1

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
                    # New Signal 2: away team confirmed riding their #1 goalie
                    if started_number_one.get((date_str, away, home)) is True:
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
            "note": "Redefined after full-season backtest: away B2B + confirmed #1 goalie starting (backup variant tested -15% ROI)",
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
