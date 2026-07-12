#!/usr/bin/env python3
"""
Generates real, statistically-derived player prop picks for TODAY's
games — replacing the old approach where Claude invented both the
pick and the odds in one call.

For every active skater in tonight's games:
  1. Pulls their real season-to-date rate (goals/game, shots/game,
     points/game, assists/game) from club-stats/now.
  2. Converts that rate into a probability using a Poisson model.
  3. Pulls REAL live market odds/lines from The Odds API.
  4. Compares model probability to market-implied probability.
  5. Only includes a pick if there's a real calculated edge (>= 3%,
     the threshold our historical backtest showed was where results
     actually turned profitable).

Also appends every generated pick to data/player_props_log.json so
today's picks become part of the permanent, growable historical record
(closing the gap where props used to just get overwritten daily).
"""
import json
import math
import os
import time
from datetime import datetime

import requests

MIN_EDGE = 0.03
MIN_GAMES_PLAYED = 10  # don't trust rate stats from a tiny sample
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

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

CATEGORY_TO_MARKET = {
    "goals": "player_goal_scorer_anytime",
    "points": "player_points",
    "shots": "player_shots_on_goal",
    "assists": "player_assists"
}


def normalize_name(name):
    return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")


def poisson_cdf(k, lam):
    if lam <= 0:
        return 1.0
    total = 0.0
    for i in range(0, k + 1):
        total += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return total


def implied_prob(american_odds):
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)


def fetch_team_stats(team):
    """Season-to-date per-player stats for one team."""
    url = f"https://api-web.nhle.com/v1/club-stats/{team}/now"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("skaters", [])
    except Exception as e:
        print(f"  Error fetching stats for {team}: {e}")
        return []


def find_todays_event(away_full, home_full):
    url = f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events?apiKey={ODDS_API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        for e in r.json():
            if e["away_team"] == away_full and e["home_team"] == home_full:
                return e["id"]
    except Exception as e:
        print(f"  Error fetching today's events: {e}")
    return None


def fetch_live_odds(event_id):
    markets = "player_shots_on_goal,player_goal_scorer_anytime,player_points,player_assists"
    url = (
        f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{event_id}/odds"
        f"?apiKey={ODDS_API_KEY}&regions=us&markets={markets}&oddsFormat=american"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Error fetching live odds: {e}")
        return None


def find_market_lines(odds_data, category, player_name):
    market_key = CATEGORY_TO_MARKET[category]
    bookmakers = odds_data.get("bookmakers", [])
    target = normalize_name(player_name)
    found = []
    for bk in bookmakers:
        for market in bk.get("markets", []):
            if market["key"] != market_key:
                continue
            outcomes = market.get("outcomes", [])
            if category == "goals":
                for o in outcomes:
                    if normalize_name(o.get("description", "")) == target and o["name"] == "Yes":
                        found.append((bk["title"], None, o["price"], None))
            else:
                over_price, under_price, point = None, None, None
                for o in outcomes:
                    if normalize_name(o.get("description", "")) == target:
                        if o["name"] == "Over":
                            over_price, point = o["price"], o.get("point")
                        elif o["name"] == "Under":
                            under_price = o["price"]
                if over_price is not None and under_price is not None:
                    found.append((bk["title"], point, over_price, under_price))
    return found


def generate_real_player_props(games_list, scratches):
    if not ODDS_API_KEY:
        print("No ODDS_API_KEY set - skipping real prop generation")
        return {"props": []}

    all_picks = []
    scratched_lower = [s.lower() for s in scratches]

    for g in games_list:
        away, home = g["away"], g["home"]
        away_full = TEAM_FULL_NAMES.get(away)
        home_full = TEAM_FULL_NAMES.get(home)
        if not away_full or not home_full:
            continue

        print(f"Processing {away} @ {home}...")
        event_id = find_todays_event(away_full, home_full)
        if not event_id:
            print(f"  No matching odds event found for {away} @ {home} - skipping")
            continue

        odds_data = fetch_live_odds(event_id)
        if not odds_data:
            continue

        for team in (away, home):
            skaters = fetch_team_stats(team)
            time.sleep(0.3)
            for p in skaters:
                first = p.get("firstName", {}).get("default", "")
                last = p.get("lastName", {}).get("default", "")
                full_name = f"{first} {last}"
                if any(sc in full_name.lower() for sc in scratched_lower):
                    continue

                gp = p.get("gamesPlayed", 0)
                if gp < MIN_GAMES_PLAYED:
                    continue

                rates = {
                    "goals": p.get("goals", 0) / gp,
                    "assists": p.get("assists", 0) / gp,
                    "points": p.get("points", 0) / gp,
                    "shots": p.get("shots", 0) / gp
                }

                for category, rate in rates.items():
                    lines = find_market_lines(odds_data, category, full_name)
                    if not lines:
                        continue
                    bookmaker, point, price_a, price_b = lines[0]

                    if category == "goals":
                        model_prob = 1 - math.exp(-rate)
                        market_prob = implied_prob(price_a)
                        edge = model_prob - market_prob
                        if edge < MIN_EDGE:
                            continue
                        all_picks.append({
                            "game": f"{away} @ {home}", "player": full_name, "team": team,
                            "category": category, "prop_type": "Anytime Goal Scorer",
                            "line": 0.5, "pick": "back", "odds": f"{'+' if price_a > 0 else ''}{price_a}",
                            "unit_size": "half" if edge < 0.06 else "full",
                            "reason": f"Model: {model_prob:.0%} chance to score vs market-implied {market_prob:.0%} "
                                      f"({rate:.2f} goals/game over {gp} GP)",
                            "model_prob": round(model_prob, 3), "market_prob": round(market_prob, 3),
                            "edge": round(edge, 3)
                        })
                    else:
                        floor_line = int(math.floor(point))
                        p_under = poisson_cdf(floor_line, rate)
                        p_over = 1 - p_under
                        over_market = implied_prob(price_a)
                        under_market = implied_prob(price_b)
                        edge_over = p_over - over_market
                        edge_under = p_under - under_market

                        if max(edge_over, edge_under) < MIN_EDGE:
                            continue

                        if edge_over >= edge_under:
                            side, model_prob, market_prob, edge, odds = "over", p_over, over_market, edge_over, price_a
                        else:
                            side, model_prob, market_prob, edge, odds = "under", p_under, under_market, edge_under, price_b

                        all_picks.append({
                            "game": f"{away} @ {home}", "player": full_name, "team": team,
                            "category": category, "prop_type": f"{category.capitalize()} {side.capitalize()}",
                            "line": point, "pick": side, "odds": f"{'+' if odds > 0 else ''}{odds}",
                            "unit_size": "half" if edge < 0.06 else "full",
                            "reason": f"Model: {model_prob:.0%} vs market-implied {market_prob:.0%} "
                                      f"({rate:.2f} {category}/game over {gp} GP)",
                            "model_prob": round(model_prob, 3), "market_prob": round(market_prob, 3),
                            "edge": round(edge, 3)
                        })

    all_picks.sort(key=lambda x: x["edge"], reverse=True)
    return {"props": all_picks[:12]}


def append_to_props_log(props, date_str):
    log_path = "data/player_props_log.json"
    try:
        with open(log_path) as f:
            log = json.load(f)
    except FileNotFoundError:
        log = []

    for p in props:
        log.append({
            "date": date_str, "game": p["game"], "player": p["player"], "team": p["team"],
            "category": p["category"], "prop_type": p["prop_type"], "line": p["line"],
            "pick": p["pick"], "odds": p["odds"], "unit_size": p["unit_size"],
            "result": None, "actual_stat": None
        })

    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"Appended {len(props)} picks to {log_path} (now {len(log)} total entries)")


if __name__ == "__main__":
    # Standalone test mode - requires data/dashboard.json and data/scratches.json to exist
    with open("data/dashboard.json") as f:
        dashboard = json.load(f)
    games_list = dashboard.get("games_tonight", [])
    try:
        with open("data/scratches.json") as f:
            scratches = json.load(f).get("scratched", [])
    except FileNotFoundError:
        scratches = []

    result = generate_real_player_props(games_list, scratches)
    print(f"\nGenerated {len(result['props'])} real edge-based picks:")
    for p in result["props"]:
        print(f"  {p['player']} ({p['team']}) - {p['prop_type']} {p['line']} @ {p['odds']} | edge: {p['edge']:.1%}")

    today = datetime.now().strftime("%Y-%m-%d")
    append_to_props_log(result["props"], today)
