#!/usr/bin/env python3
"""
build.py — Rebuild index.html with fresh tournaments.json data
Usage: python build.py
"""
import json
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "index.template.html"
INDEX = ROOT / "index.html"
DATA = ROOT / "tournaments.json"


def main():
    if not DATA.exists():
        print(f"✗ {DATA} not found. Run `python scrape_tournaments.py` first.")
        sys.exit(1)

    # Use template if exists, else use existing index.html as template
    src = TEMPLATE if TEMPLATE.exists() else INDEX
    if not src.exists():
        print(f"✗ Neither {TEMPLATE} nor {INDEX} found.")
        sys.exit(1)

    html = src.read_text(encoding="utf-8")
    data_text = DATA.read_text(encoding="utf-8")

    # Replace the embedded data block. Find the script tag and replace contents.
    pattern = re.compile(
        r'(<script id="tournament-data" type="application/json">)(.*?)(</script>)',
        re.DOTALL
    )
    new_html, n = pattern.subn(
        lambda m: f'{m.group(1)}\n{data_text}\n{m.group(3)}',
        html,
        count=1
    )

    if n == 0:
        print("✗ Could not find <script id=\"tournament-data\"> block in template.")
        sys.exit(1)

    INDEX.write_text(new_html, encoding="utf-8")

    payload = json.loads(data_text)
    count = len(payload.get("tournaments", []))
    print(f"✓ Built index.html with {count} tournaments")
    print(f"  Last updated: {payload.get('lastUpdated', '—')}")


if __name__ == "__main__":
    main()
