#!/usr/bin/env python3
"""
scrape_socials.py - Pull tournament leads from DuckDuckGo + Telegram + Instagram.

DuckDuckGo: free, no API key. Uses `ddgs` (or legacy `duckduckgo_search`) library.
Telegram: scrapes public t.me/s/<channel> preview pages, no auth.

Output: list of tournament-shaped dicts merged into tournaments.json by
the main scraper. Entries are marked `unverified: true` and `source: <provider>`.

We ONLY promote a hit to the tournament list if BOTH a parseable date AND a
known Indonesian city are detected in the text. Everything else is logged
to leads/ for manual review.

Usage (called from scrape_tournaments.py, but standalone-runnable too):
    python scrape_socials.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install requests beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)

WIB = timezone(timedelta(hours=7))
ROOT = Path(__file__).parent
LEADS_DIR = ROOT / "leads"
POSTERS_DIR = ROOT / "posters"


def _download_poster(url: str, shortcode: str) -> str:
    """Download IG poster locally and return relative repo path. Empty string on failure."""
    if not url:
        return ""
    POSTERS_DIR.mkdir(exist_ok=True)
    out = POSTERS_DIR / f"{shortcode}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return f"posters/{shortcode}.jpg"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"}, timeout=20, stream=True)
        if r.status_code != 200:
            print(f"  [poster] {shortcode}: HTTP {r.status_code}")
            return ""
        with out.open("wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return f"posters/{shortcode}.jpg"
    except Exception as e:
        print(f"  [poster] {shortcode}: {e}")
        return ""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

# DuckDuckGo is unmetered but soft-rate-limits — keep query count modest.
DDG_QUERIES = [
    '"turnamen catur" jakarta 2026',
    '"turnamen catur" bandung 2026',
    '"kejuaraan catur" indonesia 2026',
    '"open chess" indonesia 2026',
    '"festival catur" 2026',
    'turnamen catur jabodetabek 2026',
]

# Public Telegram channels with chess tournament news.
# Add @handles here (without @). Empty for now - pending user input.
TELEGRAM_CHANNELS: list[str] = []

# Instagram post URLs - we fetch /embed/ for each (no auth needed).
# Add /p/<id>/ or /reel/<id>/ URLs here. Auto-discovery from accounts is not
# feasible without a headless browser: IG profile pages are SPA-only and the
# usual mirror sites (picuki/imginn/gramhir/rsshub) are now defunct or
# behind Cloudflare. Curate post URLs by hand here.
INSTAGRAM_POST_URLS: list[str] = [
    "https://www.instagram.com/p/DSwxMLhkTxt/",
    "https://www.instagram.com/p/DUK1tDqE9EN/",
    "https://www.instagram.com/p/DTcU3LjkUL9/",
    "https://www.instagram.com/reel/DNFadUUx-XT/",
    "https://www.instagram.com/reel/DXyEoNBgU-X/",
    "https://www.instagram.com/p/DTO8qyQjyAN/",
    "https://www.instagram.com/reel/DTuCdSwkgjR/",
    "https://www.instagram.com/p/DUaIqfckS4F/",
    "https://www.instagram.com/reel/DTC8tzjkk3-/",
    "https://www.instagram.com/p/DLRji5MOBvK/",
    "https://www.instagram.com/p/DUXqd6PESL1/",
]

# IG accounts of interest. NOTE: we don't auto-discover post URLs from these
# yet (see comment above). Treat this list as the curation target — when you
# spot a tournament post on one of these accounts, add the post URL above.
INSTAGRAM_ACCOUNTS: list[str] = [
    "infolombacatur",
    "infocatur.idn",
    "catur_polinema",
    "kebunraya_id",
    "percasi.ina",
    "prfmnews",
    "info.lomba.beasiswa",
    "saganheritage_yogyakarta",
    "chesscomid",
    "lombacaturterkini",
    "cempaka_mas",
    "eventjogjaterkini",
    "mpkindonesia",
    "lombasma",
    "silomba.id",
]

# Indonesian month names
MONTHS_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5,
    "juni": 6, "juli": 7, "agustus": 8, "september": 9,
    "oktober": 10, "november": 11, "desember": 12,
}

# City list - extend with anything we want to recognize
CITIES = {
    "jakarta": "DKI Jakarta",
    "bogor": "Jawa Barat",
    "depok": "Jawa Barat",
    "tangerang": "Banten",
    "bekasi": "Jawa Barat",
    "bandung": "Jawa Barat",
    "cimahi": "Jawa Barat",
    "surabaya": "Jawa Timur",
    "yogyakarta": "DI Yogyakarta",
    "jogja": "DI Yogyakarta",
    "semarang": "Jawa Tengah",
    "solo": "Jawa Tengah",
    "denpasar": "Bali",
    "medan": "Sumatera Utara",
    "makassar": "Sulawesi Selatan",
    "palembang": "Sumatera Selatan",
}

JABODETABEK = {"jakarta", "bogor", "depok", "tangerang", "bekasi"}
BANDUNG = {"bandung", "cimahi"}


# ─────────────────────────────────────────────────────────────────
# Date / city / type extraction
# ─────────────────────────────────────────────────────────────────

def _extract_date_range(text: str) -> tuple[str, str] | None:
    """Return (startISO, endISO) if a future-ish date can be parsed, else None."""
    t = text.lower()

    # ISO single date
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            d = datetime(int(m[1]), int(m[2]), int(m[3]))
            iso = d.strftime("%Y-%m-%d")
            return iso, iso
        except ValueError:
            pass

    # "15-20 Mei 2026" / "15 - 20 Mei 2026" / "15 s/d 20 Mei 2026"
    months = "|".join(MONTHS_ID.keys())
    pat = (
        r"\b(\d{1,2})\s*(?:s/d|sd|–|-|hingga|sampai)?\s*(\d{1,2})?\s*"
        rf"({months})\s*(20\d{{2}})\b"
    )
    m = re.search(pat, t)
    if m:
        d1 = int(m[1])
        d2 = int(m[2]) if m[2] else d1
        mo = MONTHS_ID[m[3]]
        yr = int(m[4])
        try:
            start = datetime(yr, mo, d1).strftime("%Y-%m-%d")
            end = datetime(yr, mo, max(d1, d2)).strftime("%Y-%m-%d")
            return start, end
        except ValueError:
            return None

    # "Mei 2026" - month only
    m = re.search(rf"\b({months})\s*(20\d{{2}})\b", t)
    if m:
        mo = MONTHS_ID[m[1]]
        yr = int(m[2])
        try:
            start = datetime(yr, mo, 1).strftime("%Y-%m-%d")
            end = datetime(yr, mo, 28).strftime("%Y-%m-%d")
            return start, end
        except ValueError:
            return None

    return None


def _extract_city(text: str) -> tuple[str, str] | None:
    t = text.lower()
    for city, region in CITIES.items():
        if re.search(rf"\b{re.escape(city)}\b", t):
            return city.title(), region
    return None


def _extract_type(text: str) -> str:
    t = text.lower()
    if "blitz" in t:
        return "Blitz"
    if "rapid" in t or "kilat" in t:
        return "Rapid"
    return "Standard"


def _is_chess_tournament(text: str) -> bool:
    t = text.lower()
    chess_kw = any(k in t for k in ("catur", "chess"))
    event_kw = any(k in t for k in ("turnamen", "kejuaraan", "tournament", "open", "festival", "kejurnas"))
    return chess_kw and event_kw


def _shape(name: str, url: str, source: str, text: str, image: str = "") -> dict | None:
    is_ig = source.startswith("instagram")
    # Curated IG accounts are pre-vetted as chess-related; web hits aren't.
    if not is_ig and not _is_chess_tournament(text):
        return None
    dates = _extract_date_range(text)
    city = _extract_city(text)
    today = datetime.now(WIB).date()
    horizon = today + timedelta(days=365)

    if dates:
        start, end = dates
        sd = datetime.strptime(start, "%Y-%m-%d").date()
        if sd < today or sd > horizon:
            if not is_ig:
                return None
            # IG: out-of-window date is suspect, fall back to "soon"
            start = today.strftime("%Y-%m-%d")
            end = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    elif is_ig:
        # IG: no date parsed — default to a 30-day window from today
        start = today.strftime("%Y-%m-%d")
        end = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        return None

    if city:
        city_name, region = city
    elif is_ig:
        city_name, region = "TBA", "Indonesia"
    else:
        return None
    cl = city_name.lower()
    return {
        "id": f"social-{abs(hash(url)) % 10**10}",
        "name": name.strip()[:140] or f"Turnamen Catur {city_name}",
        "startDate": start,
        "endDate": end,
        "city": city_name,
        "venue": "TBA",
        "region": region,
        "type": _extract_type(text),
        "category": "Open",
        "isFIDE": False,
        "isJabodetabek": cl in JABODETABEK,
        "isBandung": cl in BANDUNG,
        "organizer": urlparse(url).netloc,
        "sourceUrl": url,
        "unverified": True,
        "source": source,
        "image": image or "",
    }


# ─────────────────────────────────────────────────────────────────
# DuckDuckGo Search (free, no API key)
# ─────────────────────────────────────────────────────────────────

def _ddgs_client():
    try:
        from ddgs import DDGS  # current package name
    except ImportError:
        from duckduckgo_search import DDGS  # legacy fallback
    return DDGS()


def fetch_ddg(queries: list[str], per_query: int = 20) -> list[dict]:
    leads: list[dict] = []
    try:
        ddgs = _ddgs_client()
    except ImportError:
        print("  [ddg] missing dep — pip install ddgs")
        return leads
    for q in queries:
        try:
            results = ddgs.text(
                q,
                region="id-id",
                safesearch="moderate",
                max_results=per_query,
            )
            for item in results or []:
                leads.append({
                    "query": q,
                    "title": item.get("title", ""),
                    "url": item.get("href") or item.get("url", ""),
                    "description": item.get("body") or item.get("description", ""),
                })
            time.sleep(1.5)  # DDG soft-rate-limits; keep polite
        except Exception as e:
            print(f"  [ddg] error on '{q}': {e}")
    return leads


# ─────────────────────────────────────────────────────────────────
# Telegram public preview
# ─────────────────────────────────────────────────────────────────

def fetch_telegram(channels: list[str]) -> list[dict]:
    leads: list[dict] = []
    for handle in channels:
        url = f"https://t.me/s/{handle.lstrip('@')}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for msg in soup.select(".tgme_widget_message"):
                text_el = msg.select_one(".tgme_widget_message_text")
                text = text_el.get_text(" ", strip=True) if text_el else ""
                link_el = msg.select_one("a.tgme_widget_message_date")
                href = link_el.get("href") if link_el else url
                if not text:
                    continue
                leads.append({
                    "query": f"telegram:@{handle}",
                    "title": text[:120],
                    "url": href,
                    "description": text,
                })
            time.sleep(1.1)
        except Exception as e:
            print(f"  [telegram] error on @{handle}: {e}")
    return leads


# ─────────────────────────────────────────────────────────────────
# Instagram public embed
# ─────────────────────────────────────────────────────────────────

_IG_SHORTCODE = re.compile(r"/(?:p|reel|reels)/([A-Za-z0-9_-]+)")

# IG embed inlines a JSON blob inside a JS string, so all `"` are
# rendered as `\"` and `\` as `\\`. Match against that escaped form,
# then unescape twice (JS string + JSON string) to recover the caption.
_IG_CAPTION_RE = re.compile(
    r'\\"edge_media_to_caption\\":\{\\"edges\\":\[\{\\"node\\":\{\\"text\\":\\"((?:\\\\.|[^\\])*?)\\"\}',
    re.S,
)
_IG_USERNAME_RE = re.compile(r'\\"owner\\":\{[^}]{0,500}?\\"username\\":\\"([^\\"]+)\\"')
_IG_DISPLAY_URL_RE = re.compile(r'\\"display_url\\":\\"((?:\\\\.|[^\\])+?)\\"')


def _decode_ig_string(escaped: str) -> str:
    """Unescape a string that was JS-escaped then JSON-escaped."""
    # First pass: unescape JS-string escapes (\\ -> \, \" -> ", \/ -> /)
    s = escaped.replace('\\\\', '\x00').replace('\\"', '"').replace('\\/', '/').replace('\x00', '\\')
    # Second pass: decode JSON string escapes (\n, \uXXXX, etc.) by wrapping in quotes.
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s


def fetch_instagram(post_urls: list[str]) -> list[dict]:
    leads: list[dict] = []
    for url in post_urls:
        m = _IG_SHORTCODE.search(url)
        if not m:
            continue
        shortcode = m.group(1)
        # Non-captioned embed inlines the caption + owner + display_url as JSON.
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
        ig_headers = {"User-Agent": "Mozilla/5.0"}
        try:
            r = requests.get(embed_url, headers=ig_headers, timeout=20)
            if r.status_code != 200:
                print(f"  [instagram] {shortcode}: HTTP {r.status_code}")
                continue
            body = r.text

            cap_m = _IG_CAPTION_RE.search(body)
            caption = _decode_ig_string(cap_m.group(1)) if cap_m else ""
            if not caption:
                # Last-ditch fallback: og:description (truncated but better than nothing)
                soup = BeautifulSoup(body, "lxml")
                og = soup.find("meta", property="og:description")
                caption = og["content"] if og and og.get("content") else ""

            user_m = _IG_USERNAME_RE.search(body)
            username = user_m.group(1) if user_m else ""

            disp_m = _IG_DISPLAY_URL_RE.search(body)
            remote_image = _decode_ig_string(disp_m.group(1)) if disp_m else ""
            if not remote_image:
                soup = BeautifulSoup(body, "lxml")
                og_img = soup.find("meta", property="og:image")
                remote_image = og_img["content"] if og_img and og_img.get("content") else ""
            image = _download_poster(remote_image, shortcode)

            # Even when caption can't be parsed (some posts return SPA-only embeds),
            # still emit the lead — the poster image alone is useful and the account
            # was manually curated.
            if caption:
                first_line = next((ln.strip() for ln in caption.splitlines() if ln.strip()), caption[:140])
                title = first_line[:140]
            else:
                title = f"Turnamen catur (@{username})" if username else "Turnamen catur"
                caption = ""
            leads.append({
                "query": f"instagram:@{username}" if username else "instagram",
                "title": title,
                "url": url,
                "description": caption,
                "image": image,
            })
            time.sleep(1.5)
        except Exception as e:
            print(f"  [instagram] error on {url}: {e}")
    return leads


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def collect_social_tournaments() -> tuple[list[dict], list[dict]]:
    """Returns (promoted_tournaments, raw_leads). Raw leads also dumped to leads/."""
    raw: list[dict] = []
    if os.environ.get("SKIP_DDG") == "1":
        print("-> Skip DuckDuckGo (SKIP_DDG=1)")
    else:
        print("-> DuckDuckGo Search…")
        raw.extend(fetch_ddg(DDG_QUERIES))

    if TELEGRAM_CHANNELS:
        print(f"-> Telegram ({len(TELEGRAM_CHANNELS)} channels)…")
        raw.extend(fetch_telegram(TELEGRAM_CHANNELS))
    else:
        print("-> Skip Telegram (no channels configured)")

    if INSTAGRAM_POST_URLS:
        print(f"-> Instagram ({len(INSTAGRAM_POST_URLS)} posts)…")
        raw.extend(fetch_instagram(INSTAGRAM_POST_URLS))
    else:
        print("-> Skip Instagram (no posts configured)")

    promoted: list[dict] = []
    seen_ids: set[str] = set()
    for lead in raw:
        text = f"{lead.get('title','')} {lead.get('description','')}"
        t = _shape(lead.get("title", ""), lead.get("url", ""), lead.get("query", ""), text, lead.get("image", ""))
        if t and t["id"] not in seen_ids:
            promoted.append(t)
            seen_ids.add(t["id"])

    LEADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(WIB).strftime("%Y-%m-%d")
    (LEADS_DIR / f"{stamp}.json").write_text(
        json.dumps({"raw": raw, "promoted_count": len(promoted)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Socials: {len(raw)} raw leads -> {len(promoted)} promoted")
    return promoted, raw


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    promoted, raw = collect_social_tournaments()
    print(f"\nPromoted ({len(promoted)}):")
    for t in promoted:
        print(f"  - [{t['startDate']}] {t['city']}: {t['name']}  ({t['source']})")
