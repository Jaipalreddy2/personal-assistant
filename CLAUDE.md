# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

**Bunty** — a 24/7 personal AI assistant Telegram bot powered by Claude. It handles Gmail, Google Calendar, LinkedIn job search and Easy Apply automation, job application tracking, stock alerts, and free-form chat. Runs on Python 3.11, macOS-optimized (uses `caffeinate`, LaunchAgent for auto-start).

## Running the bot

```bash
# Foreground (testing)
python3 bot_server.py

# Background (production)
pkill -f bot_server.py; rm -f /tmp/akshay_bot.pid
nohup python3 bot_server.py > assistant.log 2>&1 &

# Stop
pkill -f bot_server.py && rm -f /tmp/akshay_bot.pid

# Logs
tail -f assistant.log   # bot_server output
tail -f bot.log         # cron job output
```

## Install dependencies

```bash
pip3 install -r requirements.txt
python3 -m playwright install chromium
```

## One-time setup steps

```bash
# Get Telegram topic thread IDs
python3 get_topic_ids.py

# Google Calendar OAuth (generates token.json)
python3 calendar_auth.py
```

## Credentials

All secrets live in `~/.env` (outside the repo, never committed). Every script loads them with:
```python
config = dotenv_values(Path.home() / ".env")
```

Required env vars: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_GROUP_ID`, five `TELEGRAM_TOPIC_*` IDs, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD`.

Gitignored local files: `~/.env`, `credentials.json`, `token.json`, `linkedin_session.json`, `applied_jobs.db`.

## Architecture

`bot_server.py` is the main long-running process. It polls the Telegram Bot API, dispatches slash commands to the relevant module, and routes free-form text to Claude (`claude-opus-4-5` or similar). It keeps a rolling 20-message conversation history for context.

All Telegram output goes through `telegram_topics.py`, which is the single routing layer for the 5 group topic threads (Chat, Emails, Jobs, Stocks, Daily). Every other module calls `send_chat()`, `send_jobs()`, etc. from this file — never the raw Telegram API directly.

**Cron-driven scripts** run independently of the bot server:
- `morning_briefing.py` — 8am daily
- `smart_email_alert.py` — every 15 min (priority inbox watch)
- `tech_digest.py` — 8:30am weekdays

**LinkedIn automation** (`linkedin_apply.py`) uses Playwright with a saved session in `linkedin_session.json`. The flow is: parse job alert emails → send jobs to Telegram with Approve/Skip buttons → on approval, auto-apply via Easy Apply + tailor resume via Claude (`resume_tailor.py`) + message recruiter.

**Job tracking** (`job_tracker.py`) uses SQLite (`applied_jobs.db`). Stages: `applied → phone_screen → interview → offer → rejected`.

## Personalizing for a new user

1. Update the `SYSTEM_PROMPT` constant in `bot_server.py` with the user's personal details.
2. Update the `RESUME` constant in `resume_tailor.py` with the actual resume text.
3. Regenerate all Telegram IDs via `get_topic_ids.py` and update `~/.env`.

## Common issues

| Symptom | Fix |
|---|---|
| "Bot already running" on startup | `rm -f /tmp/akshay_bot.pid` |
| Telegram 409 Conflict | Two instances polling — `pkill -f bot_server.py`, wait 5s, restart |
| Calendar errors | `rm token.json && python3 calendar_auth.py` |
| LinkedIn login fails | `rm linkedin_session.json && python3 linkedin_auth.py` |
| Bot ignores group messages | Set bot privacy mode OFF via @BotFather → `/setprivacy` → Disable |
