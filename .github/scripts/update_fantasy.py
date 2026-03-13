#!/usr/bin/env python3
"""
Generates data/fantasy.json with AI-powered fantasy picks.
Uses Claude API to generate Value Plays, Goalie Starts, and Player Props.
Runs daily at 7 AM MST via GitHub Actions.
"""

import os
import json
import requests
from datetime import datetime
import pytz

MST = pytz.timezone("America/Edmonton")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def fetch_dashboard():
    """Read today's dashboard.json for game context"""
    try:
        with open("data/dashboard.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Dashboard read error: {e}")
        return {}

def call_claude(prompt):
    """Call Claude API and return parsed JSON response"""
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
        # Strip any markdown fences
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except Exception as e:
        print(f"Claude API error: {e}")
        return None

def build_game_context(dashboard):
    """Build a text summary of tonight's games for Claude"""
    games = dashboard.get("games_tonight", [])
    if not games:
        return "No games tonight."
    
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
    
    return "\n".join(lines)

def generate_value_plays(game_context, date_label):
    prompt = f"""You are an expert NHL DFS and fantasy hockey analyst. Today is {date_label}.

Tonight's NHL slate:
{game_context}

Generate fantasy value plays for both DraftKings and FanDuel. Focus on signal-informed picks where applicable — teams flagged with Signal 1 or Signal 2 should be noted. Fade B2B away teams for DFS stacks.

Respond ONLY with a valid JSON object, no markdown, no preamble. Use this exact structure:
{{
  "summary": {{
    "total_plays": 8,
    "top_tier": "S",
    "slate_size": {len(game_context.splitlines())}
  }},
  "plays": [
    {{
      "player": "Player Name",
      "team": "ABBREV",
      "position": "C/LW/RW/D",
      "tier": "S",
      "matchup": "vs OPP or @ OPP",
      "game_time": "7:00 PM ET",
      "dk_salary": "$8,400",
      "fd_salary": "$7,200",
      "proj_pts_dk": 21.4,
      "proj_pts_fd": 38.2,
      "dk_value": "2.55x",
      "fd_value": "2.31x",
      "reason": "2-3 sentence explanation focusing on matchup, recent form, signal context",
      "tags": ["DFS + Season", "Signal 1 Game"],
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

Generate 6-10 plays across S/A/B tiers. Include 1-2 avoids for any B2B away teams. Tags options: "DFS + Season", "DFS Only", "Season-Long", "Signal 1 Game", "B2B Watch", "Avoid DFS"."""

    return call_claude(prompt)

def generate_goalie_starts(game_context, date_label):
    prompt = f"""You are an expert NHL fantasy hockey analyst specializing in goalie analysis. Today is {date_label}.

Tonight's NHL slate:
{game_context}

Generate goalie start recommendations. Signal context is critical — goalies facing signal-favoured home teams get a boost, B2B away goalies are hard avoids.

Respond ONLY with a valid JSON object, no markdown, no preamble. Use this exact structure:
{{
  "goalies": [
    {{
      "name": "Goalie Name",
      "team": "ABBREV",
      "opponent": "OPP",
      "home_away": "home",
      "dk_salary": "$8,200",
      "fd_salary": "$9,000",
      "sv_pct": ".921",
      "gaa": "2.38",
      "status": "confirmed",
      "signal_note": "Signal 1 game — home team favoured" or "",
      "recommendation": "start",
      "rec_label": "▲ Start"
    }}
  ]
}}

Status options: "confirmed", "likely", "unknown", "b2b_away"
Recommendation options: "start", "stream", "wait", "avoid"
Rec label options: "▲ Start", "~ Stream", "? Wait", "✕ Avoid"
List all goalies for tonight's games. Hard avoid any B2B away goalies."""

    return call_claude(prompt)

def generate_player_props(game_context, date_label):
    prompt = f"""You are an expert NHL prop betting analyst. Today is {date_label}.

Tonight's NHL slate:
{game_context}

Generate player prop picks. Apply signal logic — B2B away players get downgraded on shot/point props, signal-favoured home players get upgrades.

Respond ONLY with a valid JSON object, no markdown, no preamble. Use this exact structure:
{{
  "props": [
    {{
      "player": "Player Name",
      "team": "ABBREV",
      "prop_type": "Anytime Goal Scorer",
      "line": "0.5",
      "odds": "+135",
      "pick": "over",
      "unit_size": "full",
      "game": "AWAY @ HOME",
      "reason": "2 sentence explanation with signal context where relevant",
      "category": "goals"
    }}
  ]
}}

Generate 8-12 props across categories: "goals", "points", "shots", "assists"
Pick options: "over", "under", "back"
Unit size options: "full", "half", "avoid"
Include at least 2 signal-informed props (upgrades or downgrades based on B2B/rest)."""

    return call_claude(prompt)

def main():
    now = datetime.now(MST)
    date_label = now.strftime("%A, %B %-d, %Y")
    today = now.strftime("%Y-%m-%d")

    print(f"Generating fantasy.json for {today}")

    # Load dashboard context
    dashboard = fetch_dashboard()
    game_context = build_game_context(dashboard)
    print(f"Game context built: {len(dashboard.get('games_tonight', []))} games")

    # Generate all three sections
    print("Generating value plays...")
    value_plays = generate_value_plays(game_context, date_label)

    print("Generating goalie starts...")
    goalie_starts = generate_goalie_starts(game_context, date_label)

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
