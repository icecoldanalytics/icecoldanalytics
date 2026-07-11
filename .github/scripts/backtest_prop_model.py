#!/usr/bin/env python3
"""
Piece 4 of 4: the actual model + backtest.

For every graded prop pick, this:
  1. Computes the player's real per-game rate using ONLY games that
     happened before that pick's date (no hindsight).
  2. Converts that rate into a probability using a Poisson model
     (standard approach for count-stat props like goals/shots/points).
  3. Compares that probability to the REAL market-implied probability
     (from real historical odds, not invented ones).
  4. Only "recommends" a side when there's a real calculated edge.
  5. Checks what actually happened (we already know, from box scores)
     and reports win rate / ROI at several edge thresholds.

Writes data/prop_model_backtest.json.
"""
import json
import math
from datetime import datetime

MIN_PRIOR_GAMES = 5

CATEGORY_TO_MARKET = {
    "goals": "player_goal_scorer_anytime",
    "points": "player_points",
    "shots": "player_shots_on_goal",
    "assists": "player_assists"
}


def normalize_name(name):
    return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")


def poisson_cdf(k, lam):
    """P(X <= k) for Poisson(lam)"""
    if lam <= 0:
        return 1.0
    total = 0.0
    for i in range(0, k + 1):
        total += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return total


def implied_prob(american_odds):
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def parse_odds_profit(american_odds):
    """Returns (profit_if_win, risk) normalized to $100-equivalent stake."""
    if american_odds > 0:
        return american_odds, 100
    else:
        return 100, abs(american_odds)


def get_player_rate(game_log, prop_date, category):
    """Average per-game rate using only games before prop_date."""
    prior = [g for g in game_log["games"] if g["date"] < prop_date]
    if len(prior) < MIN_PRIOR_GAMES:
        return None, len(prior)
    values = [g[category] for g in prior]
    avg = sum(values) / len(values)
    return avg, len(prior)


def find_market_lines(odds_entry, category, player_name):
    """Returns list of (bookmaker, point, over_price, under_price) or (bookmaker, None, yes_price, None) for goals."""
    market_key = CATEGORY_TO_MARKET[category]
    game_data = odds_entry.get("data", {})
    bookmakers = game_data.get("bookmakers", [])
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


def main():
    with open("data/player_props_log.json") as f:
        log = json.load(f)
    with open("data/player_id_map.json") as f:
        id_map = json.load(f)
    with open("data/player_game_logs.json") as f:
        game_logs = json.load(f)
    with open("data/historical_prop_odds.json") as f:
        historical_odds = json.load(f)

    graded = [e for e in log if e.get("result") in ("win", "loss")]
    print(f"Evaluating {len(graded)} graded picks against the real model...\n")

    evaluated = []
    skipped_reasons = {"no_playerid": 0, "insufficient_games": 0, "no_odds_data": 0, "no_market_match": 0}

    for e in graded:
        key = normalize_name(e["player"])
        if key not in id_map:
            skipped_reasons["no_playerid"] += 1
            continue
        player_id = str(id_map[key]["playerId"])
        if player_id not in game_logs:
            skipped_reasons["no_playerid"] += 1
            continue

        rate, n_games = get_player_rate(game_logs[player_id], e["date"], e["category"])
        if rate is None:
            skipped_reasons["insufficient_games"] += 1
            continue

        odds_key = f"{e['date']}|{e['game']}"
        if odds_key not in historical_odds:
            skipped_reasons["no_odds_data"] += 1
            continue

        lines = find_market_lines(historical_odds[odds_key], e["category"], e["player"])
        if not lines:
            skipped_reasons["no_market_match"] += 1
            continue

        # Use the first matching bookmaker's line (real market price)
        bookmaker, point, price_a, price_b = lines[0]

        if e["category"] == "goals":
            model_prob = 1 - math.exp(-rate)
            market_prob = implied_prob(price_a)
            edge = model_prob - market_prob
            actual_won = e["actual_stat"] >= 1
            evaluated.append({
                "date": e["date"], "player": e["player"], "category": e["category"],
                "pick_side": "goal_scorer", "line": None, "model_prob": round(model_prob, 3),
                "market_prob": round(market_prob, 3), "edge": round(edge, 3),
                "odds": price_a, "bookmaker": bookmaker, "n_prior_games": n_games,
                "actual_won": actual_won
            })
        else:
            floor_line = int(math.floor(point))
            p_under = poisson_cdf(floor_line, rate)
            p_over = 1 - p_under
            over_market = implied_prob(price_a)
            under_market = implied_prob(price_b)
            edge_over = p_over - over_market
            edge_under = p_under - under_market

            if edge_over >= edge_under:
                side, model_prob, market_prob, edge, odds = "over", p_over, over_market, edge_over, price_a
                actual_won = e["actual_stat"] > point
            else:
                side, model_prob, market_prob, edge, odds = "under", p_under, under_market, edge_under, price_b
                actual_won = e["actual_stat"] < point

            evaluated.append({
                "date": e["date"], "player": e["player"], "category": e["category"],
                "pick_side": side, "line": point, "model_prob": round(model_prob, 3),
                "market_prob": round(market_prob, 3), "edge": round(edge, 3),
                "odds": odds, "bookmaker": bookmaker, "n_prior_games": n_games,
                "actual_won": actual_won
            })

    print(f"Evaluated: {len(evaluated)}")
    print("Skipped:", skipped_reasons)

    def backtest_at_threshold(entries, threshold):
        picks = [x for x in entries if x["edge"] >= threshold]
        n = len(picks)
        if n == 0:
            return {"picks": 0, "wins": 0, "win_rate": 0.0, "roi": 0.0}
        wins = sum(1 for p in picks if p["actual_won"])
        total_profit, total_risk = 0.0, 0.0
        for p in picks:
            profit_if_win, risk = parse_odds_profit(p["odds"])
            total_risk += risk
            total_profit += profit_if_win if p["actual_won"] else -risk
        roi = (total_profit / total_risk * 100) if total_risk > 0 else 0.0
        return {"picks": n, "wins": wins, "win_rate": round(wins / n * 100, 1), "roi": round(roi, 1)}

    thresholds = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]
    backtest_results = {f"edge_{int(t*100)}pct": backtest_at_threshold(evaluated, t) for t in thresholds}

    output = {
        "total_graded_picks": len(graded),
        "total_evaluated_by_model": len(evaluated),
        "skipped_reasons": skipped_reasons,
        "backtest_by_edge_threshold": backtest_results,
        "all_evaluated_picks": evaluated
    }

    with open("data/prop_model_backtest.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print("BACKTEST RESULTS — Real Model vs Real Market Odds")
    print(f"{'='*60}")
    print(f"{'Min Edge':<12}{'Picks':<8}{'Win Rate':<12}{'ROI':<10}")
    for t in thresholds:
        r = backtest_results[f"edge_{int(t*100)}pct"]
        print(f"{int(t*100)}%+{'':<9}{r['picks']:<8}{r['win_rate']}%{'':<7}{r['roi']:+.1f}%")


if __name__ == "__main__":
    main()
