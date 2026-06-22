# Bunty — Personal AI Assistant

A 24/7 Telegram bot powered by Claude AI. Automates LinkedIn job search & Easy Apply, reads Gmail, manages Google Calendar, tracks job applications, monitors stocks, and handles free-form AI chat.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Module Reference](#module-reference)
- [Telegram Commands](#telegram-commands)
- [Environment Variables](#environment-variables)
- [Setup Guide](#setup-guide)
- [LinkedIn Job Automation](#linkedin-job-automation)
- [Database Schema](#database-schema)
- [Running the Bot](#running-the-bot)
- [Cron / Scheduled Tasks](#cron--scheduled-tasks)
- [Utility Scripts](#utility-scripts)
- [Troubleshooting](#troubleshooting)

---

## Features

| Feature | Description |
|---|---|
| LinkedIn Job Search | Searches Easy Apply jobs by keyword in Dublin, auto-approves fresher/graduate roles |
| LinkedIn Auto-Apply | Clicks through Easy Apply steps, uploads resume PDF, handles multi-step forms |
| External ATS Apply | Handles Greenhouse, Lever, Workday, SmartRecruiters, Ashby, BambooHR, Recruitee |
| Resume Tailoring | Claude rewrites resume bullets to match each job description |
| Recruiter Outreach | Sends personalised LinkedIn connection request to recruiter after applying |
| Job Tracker | SQLite pipeline: applied → phone_screen → interview → offer → rejected |
| Gmail Summaries | Reads inbox via IMAP, summarises with Claude, alerts on priority emails |
| Google Calendar | Create, list, delete events; add Google Meet links; natural language scheduling |
| Stock Alerts | Watches a custom ticker list for unusual drops |
| Morning Briefing | 8am daily digest of calendar, emails, and job pipeline |
| AI Chat | Full Claude conversation with rolling 20-message context about your profile |

---

## Architecture

```
Telegram Bot API
      │
      ▼
bot_server.py          ← Main loop: polls updates, dispatches commands, runs AI chat
      │
      ├── telegram_topics.py     ← Single routing layer (Chat / Jobs / Emails / Stocks / Daily topics)
      │
      ├── email_bot.py           ← Gmail IMAP reader + Claude summariser
      ├── smart_email_alert.py   ← Priority inbox watcher (runs every 15 min via cron)
      │
      ├── calendar_bot.py        ← Google Calendar API (create / list / delete events + Meet links)
      │
      ├── linkedin_apply.py      ← Playwright automation: find jobs → Easy Apply → recruiter outreach
      ├── linkedin_jobs.py       ← LinkedIn job-alert email parser → Claude summary → Telegram
      ├── linkedin_post.py       ← Generates + posts to LinkedIn via Claude
      ├── external_apply.py      ← External ATS handlers (Greenhouse, Lever, Workday, etc.)
      ├── resume_tailor.py       ← Claude-powered resume bullet rewriter per job description
      │
      ├── job_tracker.py         ← SQLite tracker + /mystatus + /update commands
      │
      ├── morning_briefing.py    ← 8am daily summary (calendar + emails + job pipeline)
      └── tech_digest.py         ← 8:30am weekday tech news digest
```

**Data flow for job application:**
```
find_jobs()
  → search_jobs()            search LinkedIn by keyword (Playwright headless browser)
  → is_fresher_role()        filter out senior roles
  → save_job() + approve     write to applied_jobs.db with status='approved'
  → apply_approved()
      → tailor_for_job()     Claude rewrites resume bullets for this specific job
      → apply_to_job()       click Easy Apply / external ATS
      → find_and_connect_recruiter()   send LinkedIn connection note
```

---

## Module Reference

### `bot_server.py`
Main long-running process. Polls Telegram Bot API, dispatches slash commands, routes free-form text to Claude with a rolling 20-message conversation history. Includes Claude Tool Use for calendar, email, stocks, and job search.

**Claude Tools wired up:**
- `create_calendar_event` — creates Google Calendar event with optional Meet link
- `list_calendar_events` — lists upcoming events
- `delete_calendar_event` — deletes event by title
- `get_job_applications` — queries the SQLite job tracker
- `fetch_emails` — reads and summarises Gmail
- `check_stocks` / `add_stock` / `remove_stock` / `list_stocks`
- `search_jobs` — triggers LinkedIn job search

### `telegram_topics.py`
Single routing layer. All other modules import from here — never call the Telegram API directly. Routes to 5 group topic threads via `message_thread_id`.

```python
send_chat(text)    # → Chat topic
send_emails(text)  # → Emails topic
send_jobs(text)    # → Jobs topic
send_stocks(text)  # → Stocks topic
send_daily(text)   # → Daily topic
```

### `linkedin_apply.py`
Core LinkedIn automation. Uses Playwright (Chromium) with a saved session (`linkedin_session.json`).

**Key functions:**

| Function | Description |
|---|---|
| `find_jobs()` | Searches all `JOB_KEYWORDS`, saves new jobs, auto-approves fresher roles, then calls `apply_approved()` |
| `apply_approved()` | Applies to all DB rows with `status='approved'` using Easy Apply |
| `auto_apply()` | Find + apply in one shot, no Telegram approval step |
| `apply_saved_jobs()` | Applies to jobs in your LinkedIn Saved Jobs list |
| `apply_to_job()` | Clicks through Easy Apply steps (Next / Review / Submit), uploads PDF resume |
| `search_jobs()` | Navigates to LinkedIn search URL, scrapes job cards |
| `find_and_connect_recruiter()` | Searches LinkedIn People for a recruiter at the company and sends a connection note |
| `login_linkedin_visible()` | Opens visible browser, auto-fills credentials, saves session |

**Job keyword list** (18 keywords, Dublin, Ireland, Easy Apply filter):
- Junior/Graduate/Associate DevOps Engineer
- Junior/Graduate Cloud Engineer
- Junior/Graduate/Entry Level Software Engineer
- Junior Platform Engineer, Junior SRE
- Junior AWS Engineer, Junior Python Developer
- Cloud Infrastructure Engineer, Junior Kubernetes Engineer
- Graduate IT Engineer, Graduate Cloud Computing

**Role filters:**
- `FRESHER_KEYWORDS` — auto-approve: junior, graduate, entry level, associate, trainee, 0-2 years, etc.
- `SENIOR_KEYWORDS` — skip: senior, lead, principal, staff, director, 5+ years, etc.

### `external_apply.py`
Handles Easy Apply jobs that redirect to a third-party ATS. Supported systems: Greenhouse, Lever, Workday, SmartRecruiters, Ashby, BambooHR, Recruitee, and a generic fallback.

Fills applicant info (name, email, phone, LinkedIn, GitHub), uploads the PDF resume, and submits.

### `resume_tailor.py`
Uses Claude to rewrite resume bullet points to match a specific job description. Fetches the job description from LinkedIn via Playwright, then prompts Claude to produce a tailored resume as plain text. Saves the result to the DB.

### `job_tracker.py`
SQLite-backed application tracker. Stages: `applied → phone_screen → interview → offer → rejected → withdrawn`.

```python
format_status_report()        # returns Markdown summary for /mystatus
handle_update_command(text)   # parses /update <id> <stage> [note]
send_daily_summary()          # sends 6pm pipeline report
```

### `email_bot.py`
Reads Gmail via IMAP SSL. Filters last N hours of inbox, skips newsletters/promos, summarises with Claude, sends to Telegram Emails topic.

### `smart_email_alert.py`
Runs every 15 minutes via cron. Looks for priority emails (job callbacks, interview invites, urgent senders) and fires an immediate Telegram alert.

### `calendar_bot.py`
Google Calendar API integration. Creates events with Google Meet links, lists upcoming events, deletes by title. OAuth token stored in `token.json`.

### `morning_briefing.py`
Runs at 8am on weekdays. Sends a combined digest: today's calendar events, unread email summary, job application pipeline count.

### `tech_digest.py`
Runs at 8:30am on weekdays. Fetches recent tech news and summarises with Claude.

### `linkedin_jobs.py`
Reads LinkedIn job-alert emails from Gmail (last 24h), extracts job titles/companies/salaries via Claude, sends a formatted summary to the Jobs Telegram topic. Used by the `/jobs` command.

### `linkedin_post.py`
Generates a LinkedIn post on a given topic via Claude and posts it to LinkedIn via the Telegram `/post` command.

### `fresh_login.py`
Opens a clean (no pre-loaded cookies) visible Chromium browser, auto-fills LinkedIn credentials, waits up to 3 minutes for login / 2FA, then saves the session to `linkedin_session.json`. Run this whenever the session expires.

---

## Telegram Commands

| Command | Module | Description |
|---|---|---|
| `/findjobs` | `linkedin_apply.py` | Search LinkedIn for Easy Apply jobs, auto-approve fresher roles, then apply |
| `/applyjobs` | `linkedin_apply.py` | Apply to all approved jobs currently in the database |
| `/savedjobs` | `linkedin_apply.py` | Apply to jobs saved in your LinkedIn Saved Jobs list |
| `/autoapply` | `linkedin_apply.py` | Find + apply with no approval step (fully automatic) |
| `/jobs` | `linkedin_jobs.py` | Summarise LinkedIn job-alert emails from the last 24h |
| `/mystatus` | `job_tracker.py` | Show full application pipeline with stage counts |
| `/update <id> <stage> [note]` | `job_tracker.py` | Update application stage (e.g. `/update 633753 interview`) |
| `/schedule` | `calendar_bot.py` | Today's Google Calendar summary |
| `/emails` | `email_bot.py` | Summarise Gmail from the last 2 hours |
| `/stocks` | `bot_server.py` | Check stock watchlist for abnormal drops |
| `/post <topic>` | `linkedin_post.py` | Generate and post to LinkedIn on the given topic |
| Free-form text | `bot_server.py` | AI chat via Claude with full personal context |

**Job update stages:** `applied` · `phone_screen` · `interview` · `offer` · `rejected` · `withdrawn`

---

## Environment Variables

All secrets live in `~/.env` (never committed). Load with `dotenv_values(Path.home() / ".env")`.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your personal chat ID (from @userinfobot) |
| `TELEGRAM_GROUP_ID` | Yes | Group ID (get via `get_topic_ids.py`) |
| `TELEGRAM_TOPIC_CHAT` | Yes | Thread ID for Chat topic |
| `TELEGRAM_TOPIC_JOBS` | Yes | Thread ID for Jobs topic |
| `TELEGRAM_TOPIC_EMAILS` | Yes | Thread ID for Emails topic |
| `TELEGRAM_TOPIC_STOCKS` | Yes | Thread ID for Stocks topic |
| `TELEGRAM_TOPIC_DAILY` | Yes | Thread ID for Daily topic |
| `GMAIL_ADDRESS` | Yes | Gmail address |
| `GMAIL_APP_PASSWORD` | Yes | Gmail App Password (not your Google password) |
| `LINKEDIN_EMAIL` | Yes | LinkedIn login email |
| `LINKEDIN_PASSWORD` | Yes | LinkedIn password |
| `PHONE` | Optional | Phone number (injected into resume and system prompt) |
| `DEGREE_BSC` | Optional | BSc degree line (e.g. `BSc Computer Science, XYZ University, 2022`) |
| `DEGREE_MSC` | Optional | MSc degree line |

---

## Setup Guide

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Create `~/.env`

```bash
# Copy the template and fill in your values
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_GROUP_ID=...
TELEGRAM_TOPIC_CHAT=2
TELEGRAM_TOPIC_JOBS=3
TELEGRAM_TOPIC_EMAILS=3
TELEGRAM_TOPIC_STOCKS=3
TELEGRAM_TOPIC_DAILY=3
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
LINKEDIN_EMAIL=you@email.com
LINKEDIN_PASSWORD=yourpassword
PHONE=+353...
DEGREE_BSC=BSc Computer Science, Your University, 2023
DEGREE_MSC=MSc Cloud Computing, National College of Ireland, 2025
```

### 3. Set up Telegram

1. Create a bot via [@BotFather](https://t.me/BotFather) → `/newbot`
2. Create a Telegram group → enable **Topics** (Settings → Topics)
3. Add your bot to the group → disable privacy mode via BotFather → `/setprivacy` → Disable
4. Run `python get_topic_ids.py` to get your group and topic thread IDs
5. Add all IDs to `~/.env`

### 4. Set up Google Calendar

```bash
# Download credentials.json from Google Cloud Console
# APIs & Services → Credentials → OAuth 2.0 Client → Desktop App
python setup_calendar.py    # opens browser for OAuth, saves token.json
```

### 5. Set up Gmail

Generate an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Use this as `GMAIL_APP_PASSWORD` — not your Google account password.

### 6. LinkedIn session

```bash
python fresh_login.py      # opens visible browser, log in manually, saves session
```

### 7. Personalise

- Edit `SYSTEM_PROMPT` in `bot_server.py` with your own name, skills, career goals
- Edit `RESUME` in `resume_tailor.py` with your actual resume text
- Edit applicant `INFO` dict in `external_apply.py` with your contact details

---

## LinkedIn Job Automation

### Commands

```bash
python linkedin_apply.py find        # find new jobs → send to Telegram for approval → apply
python linkedin_apply.py apply       # apply to all 'approved' jobs in DB
python linkedin_apply.py autoapply   # find + apply immediately, no approval step
python linkedin_apply.py savedjobs   # apply to LinkedIn Saved Jobs
python linkedin_apply.py login       # refresh LinkedIn session (visible browser)
python linkedin_apply.py resetfailed # reset all 'failed' jobs back to 'approved'
python linkedin_apply.py retryall    # reset failed + apply immediately
python linkedin_apply.py poll        # poll Telegram for ✅/❌ button taps (30s)
```

### Session Management

LinkedIn sessions expire every few days. When you see `ERR_TOO_MANY_REDIRECTS` or `ERR_HTTP_RESPONSE_CODE_FAILURE`:

```bash
python fresh_login.py     # log in manually in the browser that opens
```

The session is saved to `linkedin_session.json`. The `find_jobs` function checks session validity on startup and triggers re-login automatically if expired.

### Job Status Flow

```
pending → approved → applied
                  → failed   (Easy Apply failed — retry with resetfailed)
                  → skipped  (manually skipped via Telegram ❌ button)
```

After applying, stages progress via `/update`:
```
applied → phone_screen → interview → offer
                                   → rejected
```

---

## Database Schema

**File:** `applied_jobs.db` (SQLite)

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | LinkedIn job ID (numeric string) |
| `title` | TEXT | Job title |
| `company` | TEXT | Company name |
| `location` | TEXT | Job location |
| `url` | TEXT | LinkedIn job URL |
| `status` | TEXT | Current status: pending / approved / applied / failed / skipped |
| `stage` | TEXT | Pipeline stage: applied / phone_screen / interview / offer / rejected / withdrawn |
| `notes` | TEXT | Manual notes added via `/update` |
| `tailored_resume` | TEXT | Claude-tailored resume text for this job |
| `recruiter` | TEXT | Recruiter name if connection was sent |
| `found_at` | DATETIME | When the job was discovered |
| `applied_at` | DATETIME | When the application was submitted |

**Useful queries:**

```bash
# Check recent jobs
python show_status.py

# Check jobs by age
python check_jobs_age.py

# Check apply progress
python check_progress.py
```

---

## Running the Bot

```bash
# Foreground (testing)
python bot_server.py

# Background (production) — Windows
start /B pythonw bot_server.py

# Stop
taskkill /F /IM python.exe /FI "WINDOWTITLE eq bot_server*"

# Logs
Get-Content bot.log -Wait       # bot output
Get-Content apply_live.log -Wait  # apply output
```

If you see `Bot already running`, delete the stale PID file:
```bash
del %TEMP%\akshay_bot.pid
```

---

## Cron / Scheduled Tasks

Add these to Windows Task Scheduler or run manually:

| Time | Script | Purpose |
|---|---|---|
| 8:00am weekdays | `morning_briefing.py` | Daily digest: calendar + emails + job pipeline |
| 8:30am weekdays | `tech_digest.py` | Tech news summary |
| Every 15 min | `smart_email_alert.py` | Priority email watcher |
| 6:00pm weekdays | `job_tracker.py` (as `__main__`) | Daily job application summary |

---

## Utility Scripts

| Script | Purpose |
|---|---|
| `fresh_login.py` | Fresh LinkedIn login — no pre-loaded cookies, saves session |
| `linkedin_login_once.py` | Alternative login script |
| `grab_chrome_session.py` | Grab session cookies from your real Chrome browser |
| `save_li_at.py` | Save the `li_at` cookie manually |
| `check_session.py` | Check if current LinkedIn session is valid |
| `show_session.py` | Print current session cookie details |
| `debug_session.py` | Debug session loading issues |
| `show_status.py` | Print all jobs in the DB with current status |
| `check_progress.py` | Show apply progress summary |
| `check_jobs_age.py` | Show how old each job in the DB is |
| `reset_failed.py` | Reset failed jobs to approved |
| `run_apply.py` | Quick wrapper to run the apply step |
| `generate_resume.py` | Generate a tailored resume for a specific job |
| `scrape_profile.py` | Scrape your LinkedIn profile data |
| `get_topic_ids.py` | Print Telegram group and topic thread IDs |
| `test_apply.py` | Test the apply flow on a single job |
| `test_one_job.py` | Apply to a single specific job by ID |
| `test_job_nav.py` | Test navigation to a job page |
| `debug_job.py` | Debug a specific job's Easy Apply flow |
| `debug_saved.py` | Debug the Saved Jobs page scraping |
| `fix_urls.py` | Fix malformed URLs in the DB |
| `setup_calendar.py` | Run Google Calendar OAuth flow |
| `setup_evening.py` | Evening summary setup |
| `calendar_auth.py` | Calendar authentication helper |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERR_TOO_MANY_REDIRECTS` on job search | Session expired — run `python fresh_login.py` |
| `ERR_HTTP_RESPONSE_CODE_FAILURE` on feed | Session invalid — run `python fresh_login.py` |
| `Bot already running` on startup | `del %TEMP%\akshay_bot.pid` |
| Telegram 409 Conflict | Two bot instances running — kill all Python processes, wait 5s, restart |
| Calendar errors | `del token.json` then `python setup_calendar.py` |
| Easy Apply button not found | Job may not have Easy Apply; it will attempt external ATS handler |
| Jobs found but not applied | Run `python linkedin_apply.py apply` to apply to approved jobs in DB |
| Auto-fill fails on login page | Log in manually in the browser window — session still saves on success |
| `No approved jobs to apply to` | Run `python linkedin_apply.py find` first |

---

## Dependencies

```
anthropic>=0.40.0          Claude AI SDK
requests>=2.31.0           HTTP client
python-dotenv>=1.0.0       .env loader
playwright>=1.44.0         Browser automation (Chromium)
google-api-python-client   Google Calendar API
google-auth-httplib2       Google OAuth transport
google-auth-oauthlib       Google OAuth flow
```

Install: `pip install -r requirements.txt && python -m playwright install chromium`
