#!/usr/bin/env python3
"""
Full-season signal history + Signal 2 reconstruction.

Part 1: Walks the entire 2025-26 regular season and logs EVERY game
where Signal 1 or Signal 1 Partial fired, with results — a complete
game-by-game audit, not just aggregate stats.

Part 2: Reconstructs Signal 2 for the whole season. For every game,
it pulls the real starting goalies from NHL box scores, tracks each
team's cumulative starts chronologically, and flags "backup starts"
(the starter was NOT the team's #1 goalie by starts up to that date).
Signal 2 = Signal 1 conditions + away team started a backup.

METHOD NOTE: this uses the ACTUAL starter from each box score as a
proxy for "backup confirmed before puck drop." Starters are announced
pre-game, so this is what you'd realistically have acted on — the
only edge case is a rare last-minute goalie swap.

BACKUP DEFINITION: a starter is a "backup" if, entering that date,
they had strictly fewer starts than the team's leading goalie, AND
the team had played at least 10 games (avoids early-season noise
before a clear #1 exists).

Resumable: boxscore results cache to data/goalie_starts_cache.json,
so re-running skips already-fetched games.

Outputs:
  data/goalie_starts_cache.json  (raw per-game starter data)
  data/signal_history.json       (full game-by-game signal log)
And prints the reconstructed Signal 2 season stats.

Run:  python .github/scripts/backtest_signal2_history.py
(Takes a while on first run — roughly 1,300 boxscore fetches.)
"""

import json
import os
import time
from datetime import datetime, timedelta

import requests

NHL_TEAMS = {
    "ANA","BOS","BUF","CAR","CBJ","CGY","CHI","COL","DAL",
    "DET","EDM","FLA","LAK","MIN","MTL","NJD","NSH","NYI","NYR",
    "OTT","PHI","PIT","SEA","SJS","STL","TBL","TOR","UTA","VAN",
    "VGK","WPG","WSH"
}

SEASON_START = datetime(2025, 10, 1).date()
SEASON_END = datetime(2026, 4, 18).date()
MIN_TEAM_GAMES_FOR_BACKUP_CALL = 10

CACHE_PATH = "data/goalie_starts_cache.json"


def get_score_data(date_str):
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/score/{date_str}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Error fetching {date_str}: {e}")
        return {}


def parse_toi(toi_str):
    try:
        m, s = toi_str.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def get_starters(game_id):
    """Return (away_starter_name, home_starter_name) from the boxscore."""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore", timeout=10)
        r.raise_for_status()
        box = r.json()
    except Exception as e:
        print(f"  Boxscore error for game {game_id}: {e}")
        return None, None

    pbs = box.get("playerByGameStats", {})
    result = {}
    for side in ("awayTeam", "homeTeam"):
        goalies = pbs.get(side, {}).get("goalies", [])
        starter = None
        # Prefer an explicit starter flag if present
        for g in goalies:
            if g.get("starter") is True:
                starter = g
                break
        # Fall back to most ice time
        if starter is None and goalies:
            starter = max(goalies, key=lambda g: parse_toi(g.get("toi", "0:00")))
        result[side] = starter.get("name", {}).get("default", "") if starter else ""
    return result.get("awayTeam", ""), result.get("homeTeam", "")


def main():
    today = datetime.now().date()
    end_date = min(SEASON_END, today - timedelta(days=1))

    dates = []
    d = SEASON_START
    while d <= end_date:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    # ── Load resumable cache ──
    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                cache = json.load(f)
            print(f"Loaded cache: {len(cache)} games already fetched.")
        except Exception:
            cache = {}

    # ── Pass 1: collect all completed games + starters, chronologically ──
    all_games = []           # ordered list of game dicts
    teams_by_date = {}       # date -> set of teams playing

    print(f"Scanning season {SEASON_START} → {end_date} ({len(dates)} days)...")
    fetches_since_save = 0

    for i, date_str in enumerate(dates):
        day = get_score_data(date_str)
        teams = set()
        for g in day.get("games", []):
            state = g.get("gameState", "")
            away = g["awayTeam"]["abbrev"]
            home = g["homeTeam"]["abbrev"]
            if state in ("OFF", "FINAL", "LIVE", "CRIT", "PRE", "FUT"):
                teams.add(away)
                teams.add(home)
            if state not in ("OFF", "FINAL"):
                continue
            if away not in NHL_TEAMS or home not in NHL_TEAMS:
                continue

            game_key = f"{date_str}|{away}@{home}"
            if game_key in cache:
                entry = cache[game_key]
            else:
                away_starter, home_starter = get_starters(g["id"])
                entry = {
                    "date": date_str,
                    "away": away, "home": home,
                    "away_score": g["awayTeam"].get("score", 0),
                    "home_score": g["homeTeam"].get("score", 0),
                    "away_starter": away_starter,
                    "home_starter": home_starter
                }
                cache[game_key] = entry
                fetches_since_save += 1
                time.sleep(0.25)
                if fetches_since_save >= 25:
                    with open(CACHE_PATH, "w") as f:
                        json.dump(cache, f)
                    fetches_since_save = 0
            all_games.append(entry)
        teams_by_date[date_str] = teams
        if i % 15 == 0:
            print(f"  {date_str} · {len(all_games)} games collected")

    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)
    print(f"Season scan complete: {len(all_games)} completed games.\n")

    # ── Pass 2: walk chronologically, tracking cumulative starts,
    #            evaluating signals game by game ──
    starts = {}        # team -> {goalie_name: starts_so_far}
    team_games = {}    # team -> games played so far
    history = []
    cancelled = 0

    for g in all_games:
        date_str = g["date"]
        away, home = g["away"], g["home"]
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        prev1 = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        prev2 = (d - timedelta(days=2)).strftime("%Y-%m-%d")

        away_b2b = away in teams_by_date.get(prev1, set())
        home_b2b = home in teams_by_date.get(prev1, set())
        if home_b2b:
            home_rest = 1
        elif home in teams_by_date.get(prev2, set()):
            home_rest = 2
        else:
            home_rest = 3

        # Was tonight's away starter a backup, judged ONLY on info
        # available entering this date?
        away_starter = g.get("away_starter", "")
        team_starts = starts.get(away, {})
        gp = team_games.get(away, 0)
        backup_start = False
        if away_starter and gp >= MIN_TEAM_GAMES_FOR_BACKUP_CALL and team_starts:
            leader_starts = max(team_starts.values())
            starter_starts = team_starts.get(away_starter, 0)
            backup_start = starter_starts < leader_starts

        fade_won = g["home_score"] > g["away_score"]

        signal = None
        if away_b2b and home_b2b:
            signal = "cancelled"
            cancelled += 1
        elif away_b2b:
            if home_rest >= 3:
                signal = "signal2" if backup_start else "signal1"
            elif home_rest == 2:
                signal = "signal1_partial"

        if signal and signal != "cancelled":
            history.append({
                "date": date_str,
                "away": away, "home": home,
                "score": f"{g['away_score']}-{g['home_score']}",
                "signal": signal,
                "away_starter": away_starter,
                "backup_start": backup_start,
                "home_rest": home_rest,
                "fade_won": fade_won
            })

        # Update cumulative tracking AFTER evaluating (no hindsight)
        for team, starter in ((away, g.get("away_starter")), (home, g.get("home_starter"))):
            team_games[team] = team_games.get(team, 0) + 1
            if starter:
                starts.setdefault(team, {})
                starts[team][starter] = starts[team].get(starter, 0) + 1

    # ── Stats ──
    def calc(entries, odds=-110):
        n = len(entries)
        if n == 0:
            return {"games": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "roi": 0.0}
        wins = sum(1 for e in entries if e["fade_won"])
        profit = sum(100 if e["fade_won"] else odds for e in entries)
        return {
            "games": n, "wins": wins, "losses": n - wins,
            "win_rate": round(wins / n * 100, 1),
            "roi": round(profit / (n * abs(odds)) * 100, 1)
        }

    s1_full = [h for h in history if h["signal"] == "signal1"]
    s1p = [h for h in history if h["signal"] == "signal1_partial"]
    s2 = [h for h in history if h["signal"] == "signal2"]
    s1_combined = s1_full + s2   # Signal 2 games also meet Signal 1 conditions

    stats = {
        "signal1_all_conditions": calc(s1_combined),
        "signal1_excluding_backup_games": calc(s1_full),
        "signal1_partial": calc(s1p),
        "signal2_reconstructed": calc(s2, -108)
    }

    output = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "season": "2025-26",
        "method_notes": [
            "Signal 2 reconstructed from actual starting goalies in NHL box scores (proxy for pre-game confirmation).",
            f"Backup = starter with fewer cumulative starts than the team's leader entering that date; team must have played {MIN_TEAM_GAMES_FOR_BACKUP_CALL}+ games.",
            "ROI assumes flat stake at -110 (-108 for Signal 2), matching the live tracker's method."
        ],
        "stats": stats,
        "cancelled_both_b2b": cancelled,
        "games": history
    }

    with open("data/signal_history.json", "w") as f:
        json.dump(output, f, indent=2)

    print("=" * 62)
    print("FULL-SEASON SIGNAL HISTORY — RECONSTRUCTED")
    print("=" * 62)
    for label, key in [
        ("Signal 1 (all qualifying games)", "signal1_all_conditions"),
        ("Signal 1 (excl. backup-goalie games)", "signal1_excluding_backup_games"),
        ("Signal 1 Partial", "signal1_partial"),
        ("Signal 2 (reconstructed, backup starts)", "signal2_reconstructed"),
    ]:
        s = stats[key]
        print(f"{label:42s} {s['games']:4d} games  {s['win_rate']:5.1f}% WR  {s['roi']:+6.1f}% ROI")
    print(f"{'Cancelled (both B2B)':42s} {cancelled:4d} games")
    print(f"\nFull game-by-game log written to data/signal_history.json")

    if s2:
        print("\nReconstructed Signal 2 games:")
        for e in s2:
            mark = "✅" if e["fade_won"] else "❌"
            print(f"  {e['date']}  {e['away']} @ {e['home']}  {e['score']}  "
                  f"backup: {e['away_starter']}  {mark}")


if __name__ == "__main__":
    main()
