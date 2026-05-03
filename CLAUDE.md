# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Boss直聘 (Boss Zhipin) job listing scraper. Single-script pipeline that collects job listings from the search API then immediately fetches each job's detail description, outputting one complete CSV.

## Dependencies

- `pandas` — CSV I/O and DataFrame manipulation
- `DrissionPage` — Chromium browser automation (Chinese-friendly Selenium alternative)

No virtual environment or requirements file exists. Install globally or create one as needed.

## Scripts

### `claw.py` — Main scraper (merged pipeline)

Three phases in one run:

1. **Auto-login detection** — navigates to the search URL, waits 10s for a valid API response. If data flows → already logged in, proceeds. If timeout → prompts user to log in the popped-up browser, then automatically detects when login succeeds (no manual keypress needed).
2. **Scroll & collect** — intercepts `joblist.json` API responses while auto-scrolling to trigger pagination. Deduplicates by `securityId`.
3. **Fetch details** — for each collected job, calls `job/detail.json` to get `postDescription`.
4. **Write CSV** — merges everything into `boss_jobs.csv`.

Session cookies are persisted in `./browser_data/` via `Chromium(user_data_path="./browser_data")`, so login is only needed once.

**Configuration** (top of file):
- `CITY_CODE` — city code (default: `101280700` 珠海)
- `KEYWORD` — search keyword (default: `大数据`)
- `MAX_PAGES` — max scroll pages (default: 20)

**Run:**
```bash
python claw.py
```

**Output:** `boss_jobs.csv`

The old two-step scripts (`初步采集.py`, `深入采集.py`) are kept for reference.

## city.json

Not part of the Boss直聘 pipeline. Appears to be a captured API response (JD.com product review data). Ignored by all scripts.
