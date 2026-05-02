#!/usr/bin/env python3
"""
Catur.ID — Chess Tournament Scraper
=====================================
Scrapes chess tournaments from multiple Indonesian chess sources and outputs
tournaments.json that powers the Catur.ID web app.

Sources:
- chess-results.com (FIDE Swiss-Manager results, primary source)
- ChessPrime (cross-reference for upcoming dates)
- PB PERCASI (annual official calendar - manual seed)

Filters:
- Date range: today → today + 365 days (no backdates)
- Region focus: Jabodetabek (Jakarta, Bogor, Depok, Tangerang, Bekasi) + Bandung
- Also includes notable national events held outside the focus region

Usage:
    python scrape_tournaments.py [--quiet] [--output PATH]

Requirements:
    pip install requests beautifulsoup4 lxml
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] Missing dependencies. Install via: pip install requests beautifulsoup4 lxml")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

WIB = timezone(timedelta(hours=7))  # Jakarta time

CHESS_RESULTS_BASE = "https://chess-results.com"

# State IDs on chess-results.com — Indonesian provinces
STATE_IDS = {
    "Banten": 16,
    "DKI Jakarta": 17,
    "Jawa Barat": 18,
}

# Jabodetabek cities (case-insensitive matching)
JABODETABEK_CITIES = {
    "jakarta", "jakarta pusat", "jakarta utara", "jakarta barat",
    "jakarta timur", "jakarta selatan",
    "bogor", "kab. bogor", "kota bogor",
    "depok",
    "tangerang", "kab. tangerang", "kota tangerang", "tangerang selatan", "tangsel",
    "bekasi", "kab. bekasi", "kota bekasi",
}

BANDUNG_CITIES = {
    "bandung", "kota bandung", "kab. bandung", "bandung barat", "cimahi"
}

# Common request headers — mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Cache-Control": "no-cache",
}

# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def log(msg, quiet=False, level="INFO"):
    if quiet and level == "DEBUG":
        return
    prefix = {"INFO": "→", "DEBUG": " ·", "WARN": "⚠", "ERROR": "✗", "OK": "✓"}.get(level, "·")
    print(f"{prefix} {msg}", flush=True)


def fetch(url, retries=3, delay=2.0):
    """Fetch a URL with retry and polite delay."""
    for attempt in range(retries):
        try:
            time.sleep(delay)  # be nice to the server
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            log(f"HTTP {resp.status_code} for {url}", level="WARN")
        except requests.RequestException as e:
            log(f"Fetch error (attempt {attempt+1}/{retries}): {e}", level="WARN")
        delay *= 1.5
    return None


def classify_region(city: str, region: str = "") -> dict:
    """Classify a tournament by city → returns region flags."""
    city_l = city.lower().strip()
    region_l = region.lower().strip()

    # Check Bandung first (more specific)
    for bdg in BANDUNG_CITIES:
        if bdg in city_l:
            return {"isJabodetabek": False, "isBandung": True}

    for jbd in JABODETABEK_CITIES:
        if jbd in city_l:
            return {"isJabodetabek": True, "isBandung": False}

    return {"isJabodetabek": False, "isBandung": False}


def detect_type(name: str) -> str:
    """Detect tournament format from name."""
    n = name.lower()
    if "blitz" in n or "kilat" in n:
        return "Blitz"
    if "rapid" in n or "cepat" in n:
        return "Rapid"
    if "standard" in n or "klasik" in n or "klasic" in n:
        return "Standard"
    return "Rapid"  # most common default in Indonesia


def detect_category(name: str) -> str:
    """Detect age/group category from name."""
    n = name.lower()
    patterns = [
        (r"\bu-?(\d+)\b|\bku-?(\d+)\b", lambda m: f"U-{m.group(1) or m.group(2)}"),
    ]
    for pattern, fn in patterns:
        m = re.search(pattern, n)
        if m:
            return fn(m)

    if "junior" in n: return "Junior"
    if "pelajar" in n: return "Pelajar"
    if "wanita" in n or "putri" in n: return "Wanita"
    if "beregu" in n or "team" in n: return "Beregu"
    if "veteran" in n or "senior" in n: return "Senior"
    if "master" in n: return "Master"
    if "open" in n: return "Open"
    if "porseni" in n: return "Porseni"
    if "porprov" in n: return "Porprov"
    if "kejurnas" in n: return "Kejurnas"
    if "kejurda" in n: return "Kejurda"
    if "kejurprov" in n: return "Kejurprov"
    return "Open"


def slugify_id(name: str, fallback: str = "") -> str:
    """Generate a stable id from name."""
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return s[:60] or fallback or "untitled"


# ─────────────────────────────────────────────────────────────────
# chess-results.com scraper
# ─────────────────────────────────────────────────────────────────

def parse_chess_results_listing(html: str, region_label: str) -> list:
    """Parse a chess-results.com federation/state page listing."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    tournaments = []
    seen_ids = set()

    # Find tournament links — pattern: tnr<NUMBERS>.aspx
    for link in soup.find_all("a", href=re.compile(r"tnr\d+\.aspx")):
        href = link.get("href", "")
        match = re.search(r"tnr(\d+)\.aspx", href)
        if not match:
            continue
        tnr_id = f"tnr{match.group(1)}"
        if tnr_id in seen_ids:
            continue
        seen_ids.add(tnr_id)

        name = link.get_text(strip=True)
        if not name or len(name) < 5:
            continue

        full_url = urljoin(CHESS_RESULTS_BASE + "/", href)
        tournaments.append({
            "id": tnr_id,
            "name": name,
            "sourceUrl": full_url,
            "_region_hint": region_label,
        })

    return tournaments


def parse_tournament_detail(html: str) -> dict | None:
    """Parse an individual chess-results.com tournament page for dates and city."""
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    info = {}

    # Date: look for "Date" labels or DD.MM.YYYY ranges
    # Examples:
    #   "Date: 15.02.2026 to 25.02.2026"
    #   "Date 02.05.2026"
    date_match = re.search(
        r"Date[:\s]+(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*(?:to|–|-)\s*(\d{1,2})\.(\d{1,2})\.(\d{4}))?",
        text, re.IGNORECASE
    )
    if date_match:
        d1, m1, y1 = date_match.group(1, 2, 3)
        info["startDate"] = f"{y1}-{int(m1):02d}-{int(d1):02d}"
        if date_match.group(4):
            d2, m2, y2 = date_match.group(4, 5, 6)
            info["endDate"] = f"{y2}-{int(m2):02d}-{int(d2):02d}"
        else:
            info["endDate"] = info["startDate"]

    # Location: look for city/venue keywords
    loc_match = re.search(
        r"(?:Place|Location|Tempat|Venue|Lokasi)[:\s]+([^\n,]+(?:,\s*[^\n,]+)?)",
        text, re.IGNORECASE
    )
    if loc_match:
        info["venue"] = loc_match.group(1).strip()[:100]

    # Organizer: "Chief Organizer" or "Tournament Director"
    org_match = re.search(
        r"(?:Chief organizer|Organizer|Penyelenggara)[:\s]+([^\n]+?)(?:\s{2,}|Federation|$)",
        text, re.IGNORECASE
    )
    if org_match:
        info["organizer"] = org_match.group(1).strip()[:100]

    # Time control hint for type detection
    if re.search(r"(?:Time control|Tempo)[^\n]{0,100}rapid", text, re.IGNORECASE):
        info["type"] = "Rapid"
    elif re.search(r"(?:Time control|Tempo)[^\n]{0,100}blitz", text, re.IGNORECASE):
        info["type"] = "Blitz"
    elif re.search(r"(?:Time control|Tempo)[^\n]{0,100}\b90\b|\b120\b", text):
        info["type"] = "Standard"

    # FIDE rating hint
    if re.search(r"FIDE[\s-]?rated|valid for ELO|Rated", text, re.IGNORECASE):
        info["isFIDE"] = True

    return info if info else None


def extract_city_from_name(name: str) -> str:
    """Best-effort city extraction from tournament name."""
    n_lower = name.lower()
    # Check known cities in name
    candidates = list(JABODETABEK_CITIES) + list(BANDUNG_CITIES) + [
        "kuningan", "majalengka", "sumedang", "purwakarta", "garut", "ciamis",
        "cirebon", "subang", "indramayu", "karawang",
        "serang", "cilegon", "pandeglang", "lebak",
    ]
    for c in candidates:
        if c in n_lower:
            # Title case and clean
            return c.title().replace("Kab. ", "").replace("Kota ", "")
    return ""


def scrape_chess_results(quiet=False) -> list:
    """Scrape chess-results.com for Indonesian tournaments in target regions."""
    log("Scraping chess-results.com…", quiet=quiet)

    all_tournaments = []
    state_label_to_region = {
        "DKI Jakarta": "DKI Jakarta",
        "Jawa Barat": "Jawa Barat",
        "Banten": "Banten",
    }

    for state_label, state_id in STATE_IDS.items():
        url = f"{CHESS_RESULTS_BASE}/fed.aspx?lan=1&fed=INA&bdld1={state_id}"
        log(f"State: {state_label} (id={state_id})", quiet=quiet, level="DEBUG")

        html = fetch(url)
        if not html:
            log(f"Failed to fetch {state_label}", level="WARN")
            continue

        listing = parse_chess_results_listing(html, state_label_to_region[state_label])
        log(f"Found {len(listing)} tournaments in {state_label}", quiet=quiet, level="DEBUG")

        # Tag the region for each
        for t in listing:
            t["region"] = state_label_to_region[state_label]
            all_tournaments.append(t)

    # Deduplicate by id
    by_id = {}
    for t in all_tournaments:
        by_id[t["id"]] = t
    unique = list(by_id.values())

    log(f"Total unique tournaments from chess-results.com: {len(unique)}", quiet=quiet)
    return unique


# ─────────────────────────────────────────────────────────────────
# Annual recurring events (manual seed for major PB PERCASI events)
# ─────────────────────────────────────────────────────────────────

def annual_recurring_events(today: datetime) -> list:
    """Major recurring chess events that PB PERCASI runs annually.
    Based on historical patterns from pb-percasi.com.

    These supplement what scrapers can find since national events are often
    announced on social media or PERCASI direct rather than chess-results.com
    until close to the event date.
    """
    year = today.year
    next_year = year + 1

    return [
        # Indonesian GM Tournament (Bandung, Feb)
        {
            "id": f"annual-igmt-{next_year}",
            "name": f"Indonesian GM Tournament {next_year}",
            "startDate": f"{next_year}-02-15",
            "endDate": f"{next_year}-02-25",
            "city": "Bandung",
            "venue": "Hotel Mewangi Bandung",
            "region": "Jawa Barat",
            "type": "Standard",
            "category": "International GM",
            "isFIDE": True,
            "organizer": "PB PERCASI",
            "sourceUrl": "https://www.pb-percasi.com/",
        },
        # Pertamina Indonesian GM Tournament (Jakarta, late April)
        {
            "id": f"annual-pertamina-gm-{next_year}",
            "name": f"Pertamina Indonesian GM Tournament {next_year}",
            "startDate": f"{next_year}-04-23",
            "endDate": f"{next_year}-05-01",
            "city": "Jakarta",
            "venue": "Artotel Gelora (Hotel Century Park) Senayan",
            "region": "DKI Jakarta",
            "type": "Standard",
            "category": "International GM",
            "isFIDE": True,
            "organizer": "PB PERCASI x PT Pertamina",
            "sourceUrl": "https://www.pb-percasi.com/",
        },
        # Kejurnas Catur (Banten in 2026)
        {
            "id": f"annual-kejurnas-{year}",
            "name": f"Kejuaraan Nasional Catur ke-51 Tahun {year}",
            "startDate": f"{year}-11-09",
            "endDate": f"{year}-11-15",
            "city": "Serang",
            "venue": "TBA Provinsi Banten",
            "region": "Banten",
            "type": "Standard",
            "category": "Kejurnas",
            "isFIDE": True,
            "organizer": "PB PERCASI",
            "sourceUrl": "https://www.pb-percasi.com/",
        },
        # Kejurnas Junior
        {
            "id": f"annual-kejurnas-junior-{year}",
            "name": f"Kejurnas Catur Junior VIII Tahun {year}",
            "startDate": f"{year}-12-08",
            "endDate": f"{year}-12-14",
            "city": "Jakarta",
            "venue": "TBA",
            "region": "DKI Jakarta",
            "type": "Standard",
            "category": "Junior",
            "isFIDE": True,
            "organizer": "PB PERCASI",
            "sourceUrl": "https://www.pb-percasi.com/",
        },
    ]


# ─────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────

def enrich_tournament(t: dict, fetch_details: bool = False, quiet: bool = False) -> dict | None:
    """Enrich tournament with city, type, category, FIDE flag, and date."""
    name = t["name"]

    # Extract city from name
    city = extract_city_from_name(name)
    if not city:
        # Use region as fallback city
        city = t.get("region", "Indonesia").replace("DKI ", "")

    # Classify region
    region_flags = classify_region(city, t.get("region", ""))

    # Optional: fetch detail page for date/venue (slow — opt-in)
    detail = {}
    if fetch_details:
        log(f"Fetching detail: {t['id']}", quiet=quiet, level="DEBUG")
        detail_html = fetch(t["sourceUrl"])
        detail = parse_tournament_detail(detail_html) or {}

    # If no date from detail, skip (we don't want unknown-date entries)
    if not detail.get("startDate"):
        return None

    # Build final record
    return {
        "id": t["id"],
        "name": name,
        "startDate": detail.get("startDate"),
        "endDate": detail.get("endDate", detail.get("startDate")),
        "city": detail.get("city", city).title(),
        "venue": detail.get("venue", "TBA"),
        "region": t.get("region", "Indonesia"),
        "type": detail.get("type") or t.get("type") or detect_type(name),
        "category": t.get("category") or detect_category(name),
        "isFIDE": detail.get("isFIDE", False),
        "organizer": detail.get("organizer", t.get("organizer", "")),
        "sourceUrl": t["sourceUrl"],
        **region_flags,
    }


def filter_to_window(tournaments: list, today: datetime) -> list:
    """Keep only tournaments with end date >= today and start date <= today + 365d."""
    today_d = today.date()
    one_year_ahead = today_d + timedelta(days=365)
    out = []
    for t in tournaments:
        try:
            start = datetime.strptime(t["startDate"], "%Y-%m-%d").date()
            end = datetime.strptime(t.get("endDate", t["startDate"]), "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if end >= today_d and start <= one_year_ahead:
            out.append(t)
    return out


def main():
    parser = argparse.ArgumentParser(description="Catur.ID chess tournament scraper")
    parser.add_argument("--output", "-o", default="tournaments.json",
                        help="Output JSON file path (default: tournaments.json)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Reduce log verbosity")
    parser.add_argument("--with-details", action="store_true",
                        help="Fetch detail pages for accurate dates (SLOW: ~2s/tournament)")
    parser.add_argument("--keep-existing", action="store_true",
                        help="Merge with existing tournaments.json instead of replacing")
    args = parser.parse_args()

    today = datetime.now(WIB)
    log(f"Catur.ID Scraper — {today.strftime('%Y-%m-%d %H:%M %Z')}", quiet=args.quiet)
    log(f"Time window: {today.date()} → {(today + timedelta(days=365)).date()}",
        quiet=args.quiet)

    # 1. Scrape chess-results.com listings
    raw = scrape_chess_results(quiet=args.quiet)

    # 2. Enrich with details (city, dates) — slow if --with-details
    log(f"Enriching {len(raw)} tournaments…", quiet=args.quiet)
    enriched = []
    for i, t in enumerate(raw):
        result = enrich_tournament(t, fetch_details=args.with_details, quiet=args.quiet)
        if result:
            enriched.append(result)
        if (i + 1) % 20 == 0 and not args.quiet:
            log(f"Progress: {i+1}/{len(raw)}", quiet=args.quiet, level="DEBUG")

    log(f"Enriched: {len(enriched)} (had valid dates)", quiet=args.quiet, level="OK")

    # 3. Add annual recurring events
    annual = annual_recurring_events(today)
    for ann in annual:
        flags = classify_region(ann["city"], ann.get("region", ""))
        ann.update(flags)
    log(f"Added {len(annual)} annual recurring events", quiet=args.quiet)
    enriched.extend(annual)

    # 3b. Social leads (Brave Search + Telegram) — best-effort, marked unverified
    try:
        from scrape_socials import collect_social_tournaments
        promoted, _raw = collect_social_tournaments()
        existing_ids = {t["id"] for t in enriched}
        added = 0
        for t in promoted:
            if t["id"] not in existing_ids:
                enriched.append(t)
                added += 1
        log(f"Added {added} unverified social leads", quiet=args.quiet)
    except Exception as e:
        log(f"Socials skipped: {e}", quiet=args.quiet, level="DEBUG")

    # 4. Optionally merge with existing
    if args.keep_existing and Path(args.output).exists():
        with open(args.output, "r", encoding="utf-8") as f:
            existing = json.load(f).get("tournaments", [])
        existing_ids = {t["id"] for t in enriched}
        for t in existing:
            if t["id"] not in existing_ids:
                enriched.append(t)
        log(f"Merged with existing → {len(enriched)} total", quiet=args.quiet)

    # 5. Filter to date window
    filtered = filter_to_window(enriched, today)
    log(f"After date filter (today → +365d): {len(filtered)}", quiet=args.quiet, level="OK")

    # 6. Sort by start date
    filtered.sort(key=lambda t: t["startDate"])

    # 7. Build final payload
    payload = {
        "lastUpdated": today.isoformat(),
        "sources": [
            "chess-results.com",
            "pb-percasi.com",
            "brave-search",
            "telegram",
        ],
        "tournaments": filtered,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Wrote {len(filtered)} tournaments → {out_path}", quiet=args.quiet, level="OK")

    # Summary
    if not args.quiet:
        jbd = sum(1 for t in filtered if t.get("isJabodetabek"))
        bdg = sum(1 for t in filtered if t.get("isBandung"))
        fide = sum(1 for t in filtered if t.get("isFIDE"))
        print()
        print(f"  Jabodetabek : {jbd:>4}")
        print(f"  Bandung     : {bdg:>4}")
        print(f"  FIDE-rated  : {fide:>4}")
        print(f"  Total       : {len(filtered):>4}")
        print()


if __name__ == "__main__":
    main()
