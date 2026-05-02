# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Catur.ID — single-page Indonesian chess tournament calendar (Jabodetabek + Bandung focus, plus notable national events). Static site, no backend. README.md is in Indonesian; code/comments mix English and Indonesian.

## Common commands

```bash
# Install scraper deps
pip install requests beautifulsoup4 lxml

# Refresh data (fast — listing only, dates may be missing)
python scrape_tournaments.py

# Refresh data with detail-page fetches (slow ~2s/tournament, accurate dates)
python scrape_tournaments.py --with-details

# Optional flags: --quiet, --output PATH
# Rebuild index.html embedding the new tournaments.json
python build.py
```

No test suite, lint config, or build toolchain — just Python + a browser open on `index.html`.

## Architecture

Three-piece pipeline; data flows scraper → JSON → HTML:

1. **`scrape_tournaments.py`** — Pulls from chess-results.com (per-state via `STATE_IDS` for Banten/DKI Jakarta/Jawa Barat) and merges hardcoded annual events from `annual_recurring_events()`. Auto-classifies `isJabodetabek` / `isBandung` against the `JABODETABEK_CITIES` / `BANDUNG_CITIES` sets. Filters to today → today+365 days (no backdates). Writes `tournaments.json`.

2. **`build.py`** — Embeds `tournaments.json` into a `<script id="tournament-data" type="application/json">` block inside `index.html`. Uses `index.template.html` as the source if present, otherwise reads and rewrites `index.html` in place. The regex match is what makes the embed work — don't rename or restructure that script tag.

3. **`index.html`** — Single-file SPA (Tailwind + Alpine.js + GSAP via CDN). The whole app lives in `chessApp()` Alpine component (`x-data="chessApp()"` around line 645). It reads the embedded JSON at runtime (`document.getElementById('tournament-data')`, ~line 1963), renders both list and month-grid views, and generates ICS files client-side for calendar export.

### Tournament schema

See README.md for the full TypeScript-style interface. Key fields: `id`, `startDate`/`endDate` (ISO), `city`, `region`, `type` (Standard/Rapid/Blitz), `isFIDE`, `isJabodetabek`, `isBandung`, `sourceUrl`. The `isJabodetabek`/`isBandung` flags are computed by the scraper, not the frontend.

### Deployment

`scrape.yml` is the GitHub Actions workflow (lives in `.github/workflows/` once pushed) that runs daily at 22:00 UTC (05:00 WIB next day): scrape → build → commit if changed. Site is served from GitHub Pages (root branch). Workflow needs **Read and write** permissions on the repo for the auto-commit step. See DEPLOY.md.

## Editing notes

- Default region filter lives in `index.html` as `regionFilter: 'jabodetabek-bandung'`.
- To add a city to the focus regions, edit `JABODETABEK_CITIES` / `BANDUNG_CITIES` in `scrape_tournaments.py` (case-insensitive matching).
- To add a manually-curated annual event, edit `annual_recurring_events()` in `scrape_tournaments.py`.
- After editing `tournaments.json` directly or running the scraper, you **must** run `python build.py` — opening `index.html` won't reflect raw JSON changes.
- If `index.template.html` doesn't exist, `build.py` rewrites `index.html` in place. Be aware that hand-edits to `index.html` survive only because the regex replaces just the `<script id="tournament-data">` block.
