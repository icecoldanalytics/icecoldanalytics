#!/usr/bin/env python3
"""
Grades every logged player prop pick against real NHL box scores and
writes data/prop_stats.json (win rate / ROI, overall + by category + monthly).

Reads data/player_props_log.json — an append-only log of every prop pick
ever recommended (one entry per player/game/prop). This file should be
grown daily (see the append snippet for update_fantasy.py); it was
backfilled once from git history for Mar 13 - Apr 9, 2026.

Run manually or wire into a scheduled GitHub Action:
    pip install requests
    python .github/scripts/grade_prop_picks.py
"""

import json
import os
import re
import time
from collections import defaultdict

import requests

TEAM_ABBREV_FIX = {
    # api-web sometimes uses slightly different codes; extend as needed
}

def normalize_name(name):
    return name.strip().lower().replace(".", "").replace("'", "")


def get_game_id(date_str, away, home):
    """Look up the NHL gameId for a given date + matchup."""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/score/{date_str}", timeout=10)
        r.raise_for_status()
        data = r.json()
        for g in data.get("games", []):
            g_away = g["awayTeam"]["abbrev"]
            g_home = g["homeTeam"]["abbrev"]
            if g_away == away and g_home == home:
                if g.get("gameState") in ("OFF", "FINAL"):
                    return g["id"]
                else:
                    return None  # game not final yet, don't grade
        return None
    except Exception as e:
        print(f"  Error looking up game {away}@{home} on {date_str}: {e}")
        return None


def get_boxscore_stats(game_id):
    """Fetch player stats for a game. Returns {normalized_name: {goals, assists, points, sog}}."""
    try:
        r = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore", timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  Error fetching boxscore for game {game_id}: {e}")
        return {}

    stats = {}
    pbs = data.get("playerByGameStats", {})
    for side in ("awayTeam", "homeTeam"):
        team_data = pbs.get(side, {})
        for group in ("forwards", "defense"):
            for p in team_data.get(group, []):
                name = p.get("name", {}).get("default", "")
                if not name:
                    continue
                goals = p.get("goals", 0)
                assists = p.get("assists", 0)
                points = p.get("points", goals + assists)
                sog = p.get("sog", p.get("shots", 0))
                stats[normalize_name(name)] = {
                    "goals": goals,
                    "assists": assists,
                    "points": points,
                    "shots": sog
                }
    return stats


def parse_odds(odds_str):
    """Return (profit_if_win, risk) normalized to a $100-equivalent unit."""
    val = int(odds_str.replace("+", ""))
    if val > 0:
        return val, 100
    else:
        return 100, abs(val)


def grade_pick(pick_type, line, actual):
    line = float(line)
    if actual is None:
        return None
    if pick_type == "back":  # anytime goal scorer, line is usually 0.5
        return actual >= 1
    if pick_type == "over":
        return actual > line
    if pick_type == "under":
        return actual < line
    return None


def main():
    log_path = "data/player_props_log.json"
    if not os.path.exists(log_path):
        print(f"No log found at {log_path}")
        return

    with open(log_path) as f:
        log = json.load(f)

    # Group entries by (date, game) so we only hit the API once per game
    games_needed = defaultdict(list)
    for entry in log:
        if entry.get("result") is not None:
            continue  # already graded
        games_needed[(entry["date"], entry["game"])].append(entry)

    print(f"Grading {sum(len(v) for v in games_needed.values())} ungraded picks across {len(games_needed)} games...")

    boxscore_cache = {}
    for i, ((date_str, game), entries) in enumerate(games_needed.items()):
        away, home = [t.strip() for t in game.split("@")]
        game_id = get_game_id(date_str, away, home)
        if game_id is None:
            continue  # not final / not found yet, leave ungraded
        stats = get_boxscore_stats(game_id)
        for entry in entries:
            key = normalize_name(entry["player"])
            player_stats = stats.get(key)
            if player_stats is None:
                print(f"  Warning: no boxscore stats found for {entry['player']} ({date_str})")
                continue
            actual = player_stats.get(entry["category"].rstrip("s") if entry["category"] == "assists" else entry["category"])
            # category names already match keys: goals, assists, points, shots
            actual = player_stats.get(entry["category"])
            won = grade_pick(entry["pick"], entry["line"], actual)
            entry["actual_stat"] = actual
            entry["result"] = "win" if won else ("loss" if won is not None else None)
        if i % 10 == 0:
            print(f"  Progress: {i+1}/{len(games_needed)} games")
        time.sleep(0.5)  # be polite to the API

    # Save updated log with results filled in
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)

    # ── Compute aggregate stats ──
    graded = [e for e in log if e.get("result") in ("win", "loss")]

    def calc_stats(entries):
        n = len(entries)
        if n == 0:
            return {"picks": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "roi": 0.0}
        wins = sum(1 for e in entries if e["result"] == "win")
        losses = n - wins
        total_profit = 0.0
        total_risk = 0.0
        for e in entries:
            profit_if_win, risk = parse_odds(e["odds"])
            unit = 0.5 if e.get("unit_size") == "half" else 1.0
            risk *= unit
            profit_if_win *= unit
            total_risk += risk
            total_profit += profit_if_win if e["result"] == "win" else -risk
        roi = (total_profit / total_risk * 100) if total_risk > 0 else 0.0
        return {
            "picks": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / n * 100, 1),
            "roi": round(roi, 1)
        }

    overall = calc_stats(graded)

    by_category = {}
    for cat in ("goals", "points", "shots", "assists"):
        cat_entries = [e for e in graded if e["category"] == cat]
        by_category[cat] = calc_stats(cat_entries)

    by_month = defaultdict(list)
    for e in graded:
        by_month[e["date"][:7]].append(e)
    monthly = []
    for month in sorted(by_month):
        s = calc_stats(by_month[month])
        s["month"] = month
        monthly.append(s)

    output = {
        "generated_from": "player_props_log.json",
        "total_picks_logged": len(log),
        "total_graded": len(graded),
        "pending": len(log) - len(graded),
        "overall": overall,
        "by_category": by_category,
        "monthly": monthly
    }

    with open("data/prop_stats.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 50)
    print("PLAYER PROP PERFORMANCE")
    print("=" * 50)
    print(f"Graded:  {overall['picks']} picks")
    print(f"Wins:    {overall['wins']}")
    print(f"Losses:  {overall['losses']}")
    print(f"Win Rate:{overall['win_rate']}%")
    print(f"ROI:     {overall['roi']:+.1f}%")
    print("\nBy category:")
    for cat, s in by_category.items():
        print(f"  {cat:10s} {s['picks']:3d} picks  {s['win_rate']:5.1f}% WR  {s['roi']:+.1f}% ROI")


if __name__ == "__main__":
    main()
