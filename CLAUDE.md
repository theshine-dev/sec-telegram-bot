# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SEC Filing Telegram Bot — monitors SEC EDGAR for new filings (10-K, 10-Q, 8-K) on subscribed tickers, analyzes them with Google Gemini AI, and sends formatted results to Telegram users. Written in Python 3.13, fully async.

## Commands

```bash
# Run locally (requires ..env with valid credentials)
python main.py

# Database (PostgreSQL 16)
docker compose -f docker-compose-postgres.yml up -d

# Build & run with Docker
docker build -t sec-telegram-bot .
docker run --.env-file ..env sec-telegram-bot

# Import verification (no test suite exists)
python -c "from modules import db_manager, sec_parser, gemini_helper, telegram_helper, bg_task, ticker_validator"
```

## Architecture

### Data Flow Pipeline
```
SEC EDGAR → discover_new_filings() → analysis_queue(PENDING)
  → extract_filing_data() → get_comprehensive_analysis(Gemini)
  → send_filing_notification_to_users(Telegram) → analysis_archive
```

### Key Modules

- **`main.py`** — Entry point. Registers Telegram command handlers (`/sub`, `/unsub`, `/list`, `/start`), configures APScheduler with three interval jobs, manages lifecycle via `post_init()`/`on_shutdown()`.
- **`modules/bg_task.py`** — Orchestrator. `discover_new_filings()` finds new filings across all subscribed tickers. `process_analysis_queue()` pulls PENDING jobs respecting Gemini quota (RPM + daily limit), processes them, and counts quota only on success. Retry logic with `MAX_RETRY_LIMIT` → `PERMANENT_FAIL`.
- **`modules/sec_parser.py`** — Extracts structured data from filings via `edgartools`. 10-K/10-Q: MD&A text, risk factors, income statement numbers. 8-K: plain text. All sync `edgartools` calls wrapped in `run_in_executor`.
- **`modules/gemini_helper.py`** — Lazy-initialized Gemini client. Builds filing-type-specific prompts, requests JSON response, extracts JSON from response text via regex.
- **`modules/db_manager.py`** — Async PostgreSQL via `psycopg` + `psycopg_pool`. `get_db_connection()` is an asynccontextmanager that auto-commits/rollbacks. All DB errors propagate to callers.
- **`modules/telegram_helper.py`** — Formats Gemini analysis as HTML message. All dynamic content is `html.escape()`d. Uses singleton `Bot` instance. Per-user error handling in send loop.
- **`modules/ticker_validator.py`** — Manages ticker→CIK mapping. Downloads from SEC, caches to `data/tickers.json` and in-memory dict. `get_cik_for_ticker()` reads from memory cache.

### Config & Types (`configs/`)

- **`config.py`** — All settings from env vars: scheduler intervals, Gemini quota limits (`GEMINI_RPM_LIMIT`, `GEMINI_DAILY_LIMIT`, `MAX_RETRY_LIMIT`), paths, API credentials.
- **`types.py`** — `FilingType` enum (10-K, 10-Q, 8-K), `AnalysisStatus` enum (PENDING → COMPLETED/FAILED/PERMANENT_FAIL), `FilingInfo` and `ExtractedFilingData` dataclasses.
- **`logging_config.py`** — Rotating file handlers per domain: `bot.log`, `database.log`, `sec_api.log`, `background_process.log`, `gemini_request.log`.

## Patterns & Conventions

- **Language**: Code comments and log messages are in Korean. Telegram user-facing messages are in Korean.
- **Async wrapping**: All sync I/O (edgartools, requests, Gemini SDK) uses `asyncio.get_running_loop().run_in_executor(None, ...)`.
- **DB access pattern**: Always use `async with get_db_connection() as cur:` — yields a cursor, auto-commits on success, rollbacks + re-raises on error.
- **Quota system**: Gemini API calls tracked in `daily_quota_tracker` table. Quota counted per successful job only. Resets daily (UTC).
- **Windows dev**: `main.py` sets `WindowsSelectorEventLoopPolicy` on win32.
