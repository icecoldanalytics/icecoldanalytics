#!/usr/bin/env python3
"""
Automates data/scratches.json using the NHL's own official injury
report pages (one per team, e.g. nhl.com/blackhawks/team/injury-report)
instead of relying on manual updates.

KNOWN LIMITATION (as of this writing, July 2026 — off-season): every
team's report currently shows "no current injured players" since the
season is over. This script has been tested against that EMPTY state
successfully, but has NOT been verified against a real, populated
injury list yet, since none exist right now. Re-check this closely
once the 2026-27 season starts and some teams have actual injuries
listed — the table-parsing logic may need adjustment if the page
structure looks any different once populated.
"""
import json
import re
import time
import requests
from bs4 import BeautifulSoup

TEAM_SLUGS = {
    "ANA": "ducks", "BOS": "bruins", "BUF": "sabres", "CAR": "hurricanes",
    "CBJ": "bluejackets", "CGY": "flames", "CHI": "blackhawks", "COL": "avalanche",
    "DAL": "stars", "DET": "redwings", "EDM": "oilers", "FLA": "panthers",
    "LAK": "kings", "MIN": "wild", "MTL": "canadiens", "NJD": "devils",
    "NSH": "predators", "NYI": "islanders", "NYR": "rangers", "OTT": "senators",
    "PHI": "flyers", "PIT": "penguins", "SEA": "kraken", "SJS": "sharks",
    "STL": "blues", "TBL": "lightning", "TOR": "mapleleafs", "UTA": "utah",
    "VAN": "canucks", "VGK": "goldenknights", "WPG": "jets", "WSH": "capitals"
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_team_injuries(abbrev, slug):
    url = f"https://www.nhl.com/{slug}/team/injury-report"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

    soup = BeautifulSoup(r.text, "html.parser")
    players = []

    # Find the heading that specifically says "Injured Reserve" and only
    # look at the table that immediately follows THAT heading — not just
    # any table on the page (the page also has roster/lineup tables that
    # look superficially similar).
    heading = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        if "injured reserve" in tag.get_text(strip=True).lower():
            heading = tag
            break

    if heading is None:
        return [], None  # no injury section found at all on this page

    table = heading.find_next("table")
    if table is None:
        return [], None  # heading exists but no table follows (unusual, treat as empty)

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header row
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        first_cell_text = cells[0].get_text(strip=True)
        if not first_cell_text or "no current injured" in first_cell_text.lower():
            continue
        injury = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        players.append({"player": first_cell_text, "injury": injury, "team": abbrev})

    return players, None


def main():
    all_injured = []
    errors = []

    print(f"Checking injury reports for {len(TEAM_SLUGS)} teams...")
    for i, (abbrev, slug) in enumerate(TEAM_SLUGS.items()):
        players, error = fetch_team_injuries(abbrev, slug)
        if error:
            errors.append((abbrev, error))
            print(f"  {abbrev}: ERROR - {error}")
        else:
            if players:
                print(f"  {abbrev}: {len(players)} injured player(s) listed")
                all_injured.extend(players)
            else:
                print(f"  {abbrev}: none listed")
        time.sleep(0.4)

    scratched_names = [p["player"] for p in all_injured]

    output = {
        "scratched": scratched_names,
        "details": all_injured,
        "source": "nhl.com official injury reports",
        "note": "Auto-generated. If this list looks wrong or empty during the season, the page structure may have changed — flag for review."
    }

    with open("data/scratches.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Total injured players found: {len(scratched_names)}")
    print(f"Teams with errors: {len(errors)}")
    if errors:
        for abbrev, err in errors:
            print(f"  - {abbrev}: {err}")
    if not scratched_names:
        print("\nNOTE: zero injuries found across the entire league. During the season")
        print("this would be very unusual — if this happens once games are underway,")
        print("it likely means the scraper broke (page redesign) rather than the league")
        print("being injury-free. Worth a sanity check against nhl.com directly.")


if __name__ == "__main__":
    main()
