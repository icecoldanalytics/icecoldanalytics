#!/usr/bin/env python3
"""
Piece 2 of 4: builds data/player_game_logs.json — game-by-game stats
(goals, assists, points, shots, date) for every player we successfully
mapped to an NHL playerId. This is what lets the model compute "what
was this player's real rate heading into this specific game" instead
of using full-season numbers that include games that hadn't happened
yet.
"""
import json
import time
import requests

SEASON = "20252026"
GAME_TYPE = 2  # regular season

def main():
    with open("data/player_id_map.json") as f:
        id_map = json.load(f)

    with open("data/player_props_log.json") as f:
        log = json.load(f)

    def normalize_name(name):
        return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")

    needed_ids = {}
    for e in log:
        key = normalize_name(e["player"])
        if key in id_map:
            needed_ids[id_map[key]["playerId"]] = id_map[key]["fullName"]

    print(f"Fetching game logs for {len(needed_ids)} players...")

    all_logs = {}
    errors = []
    for i, (player_id, name) in enumerate(needed_ids.items()):
        url = f"https://api-web.nhle.com/v1/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                errors.append((name, f"HTTP {r.status_code}"))
                continue
            data = r.json()
        except Exception as e:
            errors.append((name, str(e)))
            continue

        games = []
        for g in data.get("gameLog", []):
            games.append({
                "date": g.get("gameDate"),
                "goals": g.get("goals", 0),
                "assists": g.get("assists", 0),
                "points": g.get("points", 0),
                "shots": g.get("shots", 0)
            })
        all_logs[str(player_id)] = {
            "name": name,
            "games": games
        }
        if (i + 1) % 15 == 0:
            print(f"  Progress: {i+1}/{len(needed_ids)}")
        time.sleep(0.2)

    with open("data/player_game_logs.json", "w") as f:
        json.dump(all_logs, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Successfully fetched: {len(all_logs)}")
    print(f"Failed: {len(errors)}")
    if errors:
        for name, err in errors:
            print(f"  - {name}: {err}")

    # sanity check on one player
    if all_logs:
        sample_id = next(iter(all_logs))
        sample = all_logs[sample_id]
        print(f"\nSample check — {sample['name']}: {len(sample['games'])} games logged")
        if sample["games"]:
            print("  First game:", sample["games"][0])
            print("  Last game:", sample["games"][-1])

if __name__ == "__main__":
    main()
