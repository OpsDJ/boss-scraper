# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Boss直聘 (Boss Zhipin) scraper + auto-greeting tool. Two modules:
- `collector/` — multi-city job listing & detail collection → CSV
- `auto_greet/` — collection → DeepSeek LLM evaluation → targeted greeting

## Directory Structure

```
├── collector/claw.py        # 多城市岗位采集
├── auto_greet/auto_greek.py # 采集→LLM评估→打招呼
├── scheduler.py             # 循环调度 — 完成后间隔N小时重跑，输出 时间_批次NNN
├── config.json              # 统一配置（含 schedule.loop_interval_hours）
├── data/city_codes.json     # 374个城市代码
├── output/                  # 运行时输出（gitignore）
└── .venv/                   # 项目虚拟环境（gitignore）
```

Run scripts from their respective directories (paths use `../data/` and `../output/`).

## Dependencies

Install in `.venv`: `pip install pandas drissionpage requests`

## Scripts

### `collector/claw.py` — 多城市数据采集

Loops through all 373 cities (from `data/city_codes.json`), collects job listings + details. Tracks progress in `output/city_progress.txt`, resumes on restart. Runs from collector directory.

Key config: `KEYWORD`, `MAX_PAGES`, `CITY_DELAY`. Run: `cd collector && python claw.py`.

### `auto_greet/auto_greek.py` — 智能打招呼

Four phases: (1) collect job listings from target cities, (2) fetch detail descriptions, (3) evaluate each job via DeepSeek LLM against user profile defined in `MY_PROFILE`, (4) greet only approved jobs. Runs from auto_greet directory.

Key config: `TARGET_CITIES`, `KEYWORD`, `URL_FILTERS`, `MY_PROFILE`, `DEEPSEEK_API_KEY`.

Run: `cd auto_greet && set DEEPSEEK_API_KEY=sk-xxx && python auto_greek.py`.

Output: `output/eval_results.json`, `output/approved_jobs.csv`, `output/greeted.txt`.

### `scheduler.py` — 循环任务调度

Runs collector → auto_greet in an infinite loop. After each full run completes, sleeps for
`schedule.loop_interval_hours` hours (default 6), then starts the next batch.

Output files use timestamp+batch naming: `boss_jobs_<YYYYMMDD_HHMMSS>_batch<NNN>.csv`.

Batch counter persisted in `output/batch_counter.txt` — survives restarts. Press Ctrl+C to stop gracefully.

Run: `python scheduler.py` (from project root, with `.venv` activated).

## Boss直聘 API Notes

- Job list: `GET /wapi/zpgeek/search/joblist.json` — paginated via scroll, intercepted by `tab.listen`
- Job detail: `GET /wapi/zpgeek/job/detail.json?securityId=xxx`
- Friend/add (greet): `POST /wapi/zpgeek/friend/add.json?securityId=xxx&jobId=xxx&lid=xxx` with body `sessionId=`
- Rate limit: `code=31` or message containing "频繁"/"稍后"
- Login expired: `code=3` or message containing "登录"/"未登录"
- Search URL filter params: `experience`, `degree`, `industry`, `scale` (see URL_FILTERS comments)
