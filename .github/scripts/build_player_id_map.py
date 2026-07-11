#!/usr/bin/env python3
"""
Piece 1 of 4: builds data/player_id_map.json — maps every player name
in our props log to their official NHL playerId, needed to pull
game-by-game stats in the next step.
"""
import json
import time
import requests

SEASON = "20252026"

def normalize_name(name):
    return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")

def main():
    with open("data/player_props_log.json") as f:
        log = json.load(f)

    teams = sorted(set(e["team"] for e in log))
    needed_names = set(normalize_name(e["player"]) for e in log)

    name_to_id = {}
    unmatched_teams = []

    print(f"Fetching rosters for {len(teams)} teams (season {SEASON})...")
    for i, team in enumerate(teams):
        url = f"https://api-web.nhle.com/v1/roster/{team}/{SEASON}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                print(f"  {team}: HTTP {r.status_code}, skipping")
                unmatched_teams.append(team)
                continue
            roster = r.json()
        except Exception as e:
            print(f"  {team}: error {e}")
            unmatched_teams.append(team)
            continue

        count = 0
        for group in ("forwards", "defensemen", "goalies"):
            for p in roster.get(group, []):
                first = p.get("firstName", {}).get("default", "")
                last = p.get("lastName", {}).get("default", "")
                full = f"{first} {last}"
                key = normalize_name(full)
                name_to_id[key] = {
                    "playerId": p["id"],
                    "fullName": full,
                    "team": team
                }
                count += 1
        print(f"  {team}: {count} players loaded")
        time.sleep(0.3)

    with open("data/player_id_map.json", "w") as f:
        json.dump(name_to_id, f, indent=2)

    # Check coverage
    matched = [n for n in needed_names if n in name_to_id]
    missing = [n for n in needed_names if n not in name_to_id]

    print(f"\n{'='*50}")
    print(f"Total unique players in prop log: {len(needed_names)}")
    print(f"Matched: {len(matched)}")
    print(f"Missing: {len(missing)}")
    if missing:
        print("\nMissing players (may need manual lookup or were traded):")
        for m in sorted(missing):
            print("  -", m)
    if unmatched_teams:
        print("\nTeams that failed to load:", unmatched_teams)

if __name__ == "__main__":
    main()
