#!/usr/bin/env python3
"""
Generates data/fantasy.json with AI-powered fantasy picks.
Fetches real rosters from NHL API to ensure accurate player/team data.
"""

import os
import json
import requests
from datetime import datetime
import pytz

MST = pytz.timezone("America/Edmonton")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def fetch_dashboard():
    try:
        with open("data/dashboard.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Dashboard read error: {e}")
        return {}

def fetch_rosters(games):
    """Fetch real rosters with stats from NHL API"""
    rosters = {}
    for g in games:
        for team in [g["away"], g["home"]]:
            if team in rosters:
                continue
            try:
                url = f"https://api-web.nhle.com/v1/club-stats/{team}/now"
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                data = r.json()

                # Calculate team average games played to detect injured players
                all_gp = [p.get("gamesPlayed", 0) for p in data.get("skaters", [])]
                avg_gp = sum(all_gp) / len(all_gp) if all_gp else 0
                min_gp = avg_gp * 0.4  # Flag if played less than 40% of team average

                skaters = []
                for p in data.get("skaters", []):
                    fn = p.get("firstName", {}).get("default", "")
                    ln = p.get("lastName", {}).get("default", "")
                    pos = p.get("positionCode", "")
                    gp = p.get("gamesPlayed", 0)
                    pts = p.get("points", 0)
                    goals = p.get("goals", 0)
                    shots = p.get("shots", 0)
                    toi = round(p.get("avgTimeOnIcePerGame", 0) / 60, 1)

                    # Skip likely injured (very low games played vs team avg)
                    if gp < min_gp:
                        print(f"  Skipping likely injured: {fn} {ln} ({gp} GP vs {avg_gp:.0f} avg)")
                        continue

                    skaters.append(f"{fn} {ln} ({pos}, {gp}GP, {goals}G {pts}PTS, {shots}SOG, {toi}min TOI)")

                goalies = []
                for p in data.get("goalies", []):
                    fn = p.get("firstName", {}).get("default", "")
                    ln = p.get("lastName", {}).get("default", "")
                    gp = p.get("gamesPlayed", 0)
                    gs = p.get("gamesStarted", 0)
                    sv = round(p.get("savePercentage", 0), 3)
                    gaa = round(p.get("goalsAgainstAverage", 0), 2)
                    goalies.append(f"{fn} {ln} ({gp}GP, {gs}GS, .{str(sv)[2:]} SV%, {gaa} GAA)")

                rosters[team] = {"skaters": skaters[:20], "goalies": goalies}
                print(f"✓ Roster fetched: {team} — {len(skaters)} active skaters, {len(goalies)} goalies")
            except Exception as e:
                print(f"Roster fetch error for {team}: {e}")
                rosters[team] = {"skaters": [], "goalies": []}
    return rosters

def call_claude(prompt):
    if not ANTHROPIC_API_KEY:
        print("No Anthropic API key")
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=60
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"]
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except Exception as e:
        print(f"Claude API error: {e}")
        return None

def build_game_context(dashboard, rosters):
    games = dashboard.get("games_tonight", [])
    if not games:
        return "No games tonight.", []

    lines = []
    for g in games:
        signal_note = ""
        if g["signal"] == "sig1":
            signal_note = f" [SIGNAL 1 — fade {g['away']}, home {g['home']} rested {g['home_rest']}+ days]"
        elif g["signal"] == "partial":
            signal_note = f" [SIGNAL 1 PARTIAL — fade {g['away']}, home rested 2 days]"
        elif g["signal"] == "cancel":
            signal_note = " [BOTH B2B — signals cancel]"

        odds_note = ""
        if g.get("away_ml") and g.get("home_ml"):
            odds_note = f" | ML: {g['away']} {g['away_ml']} / {g['home']} {g['home_ml']}"

        lines.append(f"- {g['away']} @ {g['home']} · {g['time_et']}{odds_note}{signal_note}")

        # Add roster info
        for team in [g["away"], g["home"]]:
            if team in rosters and rosters[team]["skaters"]:
                lines.append(f"  {team} skaters: {', '.join(rosters[team]['skaters'])}")
                lines.append(f"  {team} goalies: {', '.join(rosters[team]['goalies'])}")

    return "\n".join(lines), games

def generate_value_plays(game_context, date_label, n_games):
    prompt = f"""You are an expert NHL DFS and fantasy hockey analyst. Today is {date_label}.

Tonight's NHL slate with CONFIRMED CURRENT ROSTERS:
{game_context}

CRITICAL INSTRUCTION — YOU MUST FOLLOW THIS:
The rosters listed above are the ONLY source of truth for tonight's players.
Your training data about NHL rosters is OUTDATED — trades have happened, players have moved teams.
DO NOT use any player not explicitly listed above.
DO NOT use Mitch Marner on Toronto — he was traded.
DO NOT use any player whose name does not appear in the roster lists above.
If you cannot find enough players from the lists above, use fewer picks. Never invent or assume roster assignments.
Generate fantasy value plays for both DraftKings and FanDuel. Apply signal logic where flagged.

Respond ONLY with valid JSON, no markdown. Use this exact structure:
{{
  "summary": {{
    "total_plays": 8,
    "top_tier": "S",
    "slate_size": {n_games}
  }},
  "plays": [
    {{
      "player": "First Last",
      "team": "ABBREV",
      "position": "C",
      "tier": "S",
      "matchup": "vs OPP or @ OPP",
      "game_time": "7:00 PM ET",
      "dk_salary": "$8,400",
      "fd_salary": "$7,200",
      "proj_pts_dk": 21.4,
      "proj_pts_fd": 38.2,
      "dk_value": "2.55x",
      "fd_value": "5.31x",
      "reason": "2-3 sentence explanation with signal context where relevant",
      "tags": ["DFS + Season"],
      "format": "both"
    }}
  ],
  "avoids": [
    {{
      "team": "ABBREV",
      "reason": "Signal 1 fade — B2B away",
      "tag": "Avoid DFS"
    }}
  ]
}}

Generate 6-10 plays across S/A/B tiers. Tags: "DFS + Season", "DFS Only", "Season-Long", "Signal 1 Game", "B2B Watch", "Avoid DFS"."""

    return call_claude(prompt)

def generate_goalie_starts(game_context, date_label, rosters, games):
    # Build goalie-specific context
    goalie_lines = []
    for g in games:
        away = g["away"]
        home = g["home"]
        signal_note = ""
        if g["signal"] == "sig1":
            signal_note = f"SIGNAL 1 — home goalie boosted, away goalie downgraded"
        elif g["signal"] == "cancel":
            signal_note = "BOTH B2B — signals cancel"

        away_goalies = rosters.get(away, {}).get("goalies", ["Unknown"])
        home_goalies = rosters.get(home, {}).get("goalies", ["Unknown"])
        goalie_lines.append(f"- {away} @ {home} · {g['time_et']}{' | ' + signal_note if signal_note else ''}")
        goalie_lines.append(f"  {away} goalies: {', '.join(away_goalies)}")
        goalie_lines.append(f"  {home} goalies: {', '.join(home_goalies)}")

    goalie_context = "\n".join(goalie_lines)

    prompt = f"""You are an expert NHL fantasy hockey analyst. Today is {date_label}.

Tonight's games with CONFIRMED CURRENT GOALIES:
{goalie_context}

CRITICAL: The goalies listed above are the ONLY source of truth. Your training data is outdated. Only use goalies explicitly listed above.
Generate goalie start recommendations. Signal context is critical.

Respond ONLY with valid JSON, no markdown:
{{
  "goalies": [
    {{
      "name": "First Last",
      "team": "ABBREV",
      "opponent": "OPP",
      "home_away": "home",
      "dk_salary": "$8,200",
      "fd_salary": "$9,000",
      "sv_pct": ".921",
      "gaa": "2.38",
      "status": "confirmed",
      "signal_note": "",
      "recommendation": "start",
      "rec_label": "▲ Start"
    }}
  ]
}}

Status: "confirmed", "likely", "unknown", "b2b_away"
Recommendation: "start", "stream", "wait", "avoid"
Rec label: "▲ Start", "~ Stream", "? Wait", "✕ Avoid"
List one goalie per team. Hard avoid B2B away goalies."""

    return call_claude(prompt)

def generate_player_props(game_context, date_label):
    prompt = f"""You are an expert NHL prop betting analyst. Today is {date_label}.

Tonight's NHL slate with CONFIRMED CURRENT ROSTERS:
{game_context}

CRITICAL: Only use players listed above. Do not use players from your training data.

Generate player prop picks applying signal logic where relevant.

Respond ONLY with valid JSON, no markdown:
{{
  "props": [
    {{
      "player": "First Last",
      "team": "ABBREV",
      "prop_type": "Anytime Goal Scorer",
      "line": "0.5",
      "odds": "+135",
      "pick": "over",
      "unit_size": "full",
      "game": "AWAY @ HOME",
      "reason": "2 sentence explanation with signal context",
      "category": "goals"
    }}
  ]
}}

Generate 8-12 props. Categories: "goals", "points", "shots", "assists"
Pick: "over", "under", "back"
Unit size: "full", "half", "avoid"."""

    return call_claude(prompt)

def main():
    now = datetime.now(MST)
    date_label = now.strftime("%A, %B %-d, %Y")
    today = now.strftime("%Y-%m-%d")

    print(f"Generating fantasy.json for {today}")

    dashboard = fetch_dashboard()
    games = dashboard.get("games_tonight", [])

    if not games:
        print("No games tonight — skipping fantasy generation")
        return

    print(f"Fetching rosters for {len(games)} games...")
    rosters = fetch_rosters(games)

    game_context, games_list = build_game_context(dashboard, rosters)

    print("Generating value plays...")
    value_plays = generate_value_plays(game_context, date_label, len(games))

    print("Generating goalie starts...")
    goalie_starts = generate_goalie_starts(game_context, date_label, rosters, games_list)

    print("Generating player props...")
    player_props = generate_player_props(game_context, date_label)

    if not value_plays or not goalie_starts or not player_props:
        print("❌ One or more sections failed — aborting")
        return

    output = {
        "date": today,
        "date_label": date_label,
        "value_plays": value_plays,
        "goalie_starts": goalie_starts,
        "player_props": player_props
    }

    os.makedirs("data", exist_ok=True)
    with open("data/fantasy.json", "w") as f:
        json.dump(output, f, indent=2)

    n_plays = len(value_plays.get("plays", []))
    n_goalies = len(goalie_starts.get("goalies", []))
    n_props = len(player_props.get("props", []))
    print(f"✓ fantasy.json written — {n_plays} plays, {n_goalies} goalies, {n_props} props")

if __name__ == "__main__":
    main()
