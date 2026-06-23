#!/usr/bin/env python3
"""
Bunty — Akshay's personal AI assistant Telegram bot.
Runs continuously, responds to messages via Claude, and accepts commands.
"""

import requests
import anthropic
import time
import json
import os
import sys
import tempfile
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import dotenv_values
from calendar_bot import get_calendar_summary
from linkedin_jobs import get_job_summary
from linkedin_post import post_from_topic
from job_tracker import format_status_report, handle_update_command
import subprocess

# Runtime paths — resolved dynamically so the repo works on any machine
BASE       = Path(__file__).parent
PYTHON     = sys.executable
LAST_EMAIL_FILE = BASE / "last_email_check.txt"
STOCKS_DIR = Path.home() / "stockspredictor"

# Prevent duplicate instances
PIDFILE = Path(tempfile.gettempdir()) / "akshay_bot.pid"
if PIDFILE.exists():
    old_pid = int(PIDFILE.read_text().strip())
    try:
        os.kill(old_pid, 0)  # Check if process alive
        print(f"Bot already running (PID {old_pid}). Exiting.")
        sys.exit(0)
    except OSError:
        pass  # Process dead, stale PID file — continue
PIDFILE.write_text(str(os.getpid()))

import atexit
atexit.register(lambda: PIDFILE.unlink(missing_ok=True))

config = dotenv_values(Path.home() / ".env")

ANTHROPIC_KEY  = config.get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = config.get("TELEGRAM_CHAT_ID")

TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Conversation history for context (last 20 messages)
conversation_history = []

_phone = config.get("PHONE", "")
_bsc   = config.get("DEGREE_BSC", "")
_msc   = config.get("DEGREE_MSC", "")

SYSTEM_PROMPT = f"""You are Bunty, Jaipal Kasi Reddy's personal AI assistant. Here's everything you know about him:

PERSONAL:
- Full name: Jaipal Kasi Reddy
- Email: kasireddyjaipal02@gmail.com | Phone: {_phone}
- Location: Dublin, County Dublin, Ireland
- LinkedIn: linkedin.com/in/jaipal-kasireddy-375a5227b
- GitHub: github.com/Jaipalreddy2
- Pronouns: He/Him

EDUCATION:
- {_msc}
- {_bsc}

CURRENT STATUS:
- Full-time student, available for part-time / internship now
- Available for full-time roles from February 2027
- Open to: Cloud Engineer | DevOps Engineer | Graduate Programme | IT Systems roles
- Work modes: Dublin on-site, Hybrid, or Remote

TECHNICAL SKILLS:
- Cloud: AWS (EC2, S3, IAM, CloudFormation — learning)
- DevOps: Docker, Kubernetes, CI/CD Pipelines (GitHub Actions)
- OS: Linux (command line, shell scripting)
- Programming: Python, SQL
- Tools: Git, GitHub

LINKEDIN ABOUT (his own words):
"I am a Master's student in Cloud Computing at the National College of Ireland (NCI), Dublin, currently seeking internship, part-time, and graduate opportunities in Cloud Engineering, DevOps, and Software Development. With a strong foundation in cloud technologies, I am passionate about building scalable, reliable, and secure cloud infrastructure. I am actively developing skills in AWS, Git, GitHub, Linux, Docker, Kubernetes, CI/CD pipelines, SQL and Python."

PROJECTS:
- personal-assistant: This Telegram bot — Gmail + LinkedIn job automation + Claude AI (Python, Playwright, Telegram API)
- TODO: Add any university projects or personal cloud/DevOps projects

GOALS & INTERESTS:
- Land a Cloud Engineer or DevOps Engineer role in Dublin (fresher / graduate level)
- Build AWS certifications
- Gain hands-on experience with Kubernetes and Terraform in production

Be concise, friendly, and helpful. Keep responses short — this is Telegram, not an essay.
Use emojis occasionally. Help with coding, cloud/DevOps advice, career questions, and anything else he needs."""


def send_message(text, parse_mode="Markdown", thread_id=None):
    """Send a message to the group chat topic."""
    from telegram_topics import GROUP_ID, TOPICS
    payload = {
        "chat_id":    GROUP_ID,
        "text":       text,
        "parse_mode": parse_mode,
        "message_thread_id": thread_id if thread_id else TOPICS["chat"],
    }
    resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    return resp.ok


def get_updates(offset=None):
    """Poll Telegram for new messages and callback queries."""
    params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
    if offset:
        params["offset"] = offset
    resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
    if not resp.ok:
        data = resp.json()
        if data.get("error_code") == 409:
            print("409 Conflict — another instance running, waiting 60s...")
            time.sleep(60)
        return {"result": []}
    return resp.json()


def is_authorized(msg):
    """Accept messages from the group or the personal chat."""
    chat = msg.get("chat", {})
    chat_id   = str(chat.get("id", ""))
    chat_type = chat.get("type", "")
    from telegram_topics import GROUP_ID
    return chat_id == TELEGRAM_CHAT or chat_id == str(GROUP_ID) or chat_type in ("group", "supergroup")


TOOLS = [
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event for Akshay. If attendee emails are provided, send them a Google Meet invite. Always add a Google Meet link when scheduling a meeting with other people.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":      {"type": "string", "description": "Event title"},
                "date":       {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "start_time": {"type": "string", "description": "Start time in HH:MM 24h format"},
                "end_time":   {"type": "string", "description": "End time in HH:MM 24h format"},
                "location":   {"type": "string", "description": "Optional physical location"},
                "attendees":  {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses — they will receive a Google Meet invite"},
                "add_meet":   {"type": "boolean", "description": "Add a Google Meet video link (default true when attendees present)"}
            },
            "required": ["title", "date", "start_time", "end_time"]
        }
    },
    {
        "name": "list_calendar_events",
        "description": "List Akshay's upcoming calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days ahead to look (default 7)"}
            }
        }
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete a calendar event by title (and optional date).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date":  {"type": "string", "description": "YYYY-MM-DD, optional"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "get_job_applications",
        "description": "Get Akshay's job application pipeline from the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "description": "Filter by stage: applied, phone_screen, interview, offer, rejected. Leave empty for all."}
            }
        }
    },
    {
        "name": "fetch_emails",
        "description": "Fetch and summarize Akshay's recent Gmail emails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How many hours back to look (default 2)"}
            }
        }
    },
    {
        "name": "check_stocks",
        "description": "Trigger a stock drop check for Akshay's watchlist.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "add_stock",
        "description": "Add a stock ticker to Akshay's watchlist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol e.g. AAPL, TSLA"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "remove_stock",
        "description": "Remove a stock ticker from Akshay's watchlist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol to remove"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "list_stocks",
        "description": "List all stocks currently in Akshay's watchlist.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "search_jobs",
        "description": "Search LinkedIn for new Easy Apply jobs matching Akshay's profile.",
        "input_schema": {"type": "object", "properties": {}}
    }
]


def execute_tool(name, params):
    """Run a tool and return a string result."""
    try:
        if name == "create_calendar_event":
            from calendar_bot import get_calendar_service
            import uuid
            svc = get_calendar_service()
            date = params["date"]
            attendees = params.get("attendees") or []
            add_meet = params.get("add_meet", bool(attendees))
            event = {
                "summary": params["title"],
                "start": {"dateTime": f"{date}T{params['start_time']}:00", "timeZone": "Europe/Dublin"},
                "end":   {"dateTime": f"{date}T{params['end_time']}:00",   "timeZone": "Europe/Dublin"},
            }
            if params.get("location"):
                event["location"] = params["location"]
            if attendees:
                event["attendees"] = [{"email": e} for e in attendees]
            if add_meet:
                event["conferenceData"] = {
                    "createRequest": {"requestId": str(uuid.uuid4()), "conferenceSolutionKey": {"type": "hangoutsMeet"}}
                }
            created = svc.events().insert(
                calendarId="primary", body=event,
                conferenceDataVersion=1 if add_meet else 0,
                sendUpdates="all" if attendees else "none"
            ).execute()
            meet_link = created.get("hangoutLink") or (created.get("conferenceData") or {}).get("entryPoints", [{}])[0].get("uri", "")
            result = f"✅ Created: *{created['summary']}* on {date} {params['start_time']}–{params['end_time']}"
            if meet_link:
                result += f"\n🎥 Meet link: {meet_link}"
            if attendees:
                result += f"\n📧 Invites sent to: {', '.join(attendees)}"
            return result

        elif name == "list_calendar_events":
            from calendar_bot import get_calendar_summary
            from telegram_topics import send_daily
            summary = get_calendar_summary()
            send_daily(summary)
            return "📅 Calendar posted to Daily topic."

        elif name == "delete_calendar_event":
            from calendar_bot import get_calendar_service
            from datetime import datetime, timezone, timedelta
            svc = get_calendar_service()
            now = datetime.now(timezone.utc)
            result = svc.events().list(
                calendarId="primary", timeMin=now.isoformat(),
                timeMax=(now + timedelta(days=60)).isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=50
            ).execute()
            title_lower = params["title"].lower()
            date_filter = params.get("date", "")
            for e in result.get("items", []):
                if title_lower in e.get("summary", "").lower():
                    start = e["start"].get("dateTime", e["start"].get("date", ""))
                    if not date_filter or date_filter in start:
                        svc.events().delete(calendarId="primary", eventId=e["id"]).execute()
                        return f"✅ Deleted: {e['summary']}"
            return f"❌ No event found matching '{params['title']}'"

        elif name == "get_job_applications":
            from job_tracker import format_status_report
            return format_status_report()

        elif name == "fetch_emails":
            from email_bot import fetch_recent_emails, summarize_with_claude
            emails = fetch_recent_emails(hours=params.get("hours", 2))
            return summarize_with_claude(emails)

        elif name == "check_stocks":
            subprocess.Popen(
                [PYTHON, str(STOCKS_DIR / "stock_alerts.py")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📊 Stock check triggered — results coming to Stocks topic shortly."

        elif name == "add_stock":
            import sqlite3
            ticker = params["ticker"].upper().strip()
            db = str(STOCKS_DIR / "stocks_vanguard.db")
            conn = sqlite3.connect(db)
            existing = conn.execute("SELECT ticker FROM favorites WHERE ticker=?", (ticker,)).fetchone()
            if existing:
                conn.close()
                return f"📊 {ticker} is already in your watchlist."
            conn.execute("INSERT INTO favorites (ticker) VALUES (?)", (ticker,))
            conn.commit()
            conn.close()
            return f"✅ Added *{ticker}* to your stock watchlist."

        elif name == "remove_stock":
            import sqlite3
            ticker = params["ticker"].upper().strip()
            db = str(STOCKS_DIR / "stocks_vanguard.db")
            conn = sqlite3.connect(db)
            deleted = conn.execute("DELETE FROM favorites WHERE ticker=?", (ticker,)).rowcount
            conn.commit()
            conn.close()
            if deleted:
                return f"✅ Removed *{ticker}* from your watchlist."
            return f"❌ {ticker} wasn't in your watchlist."

        elif name == "list_stocks":
            import sqlite3
            db = str(STOCKS_DIR / "stocks_vanguard.db")
            conn = sqlite3.connect(db)
            tickers = [r[0] for r in conn.execute("SELECT ticker FROM favorites ORDER BY ticker").fetchall()]
            conn.close()
            if tickers:
                return "📊 Your watchlist: " + ", ".join(tickers)
            return "📊 Your watchlist is empty."

        elif name == "search_jobs":
            subprocess.Popen(
                [PYTHON, str(BASE / "linkedin_apply.py"), "find"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "🔍 Job search triggered — results coming to Jobs topic shortly."

        return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error ({name}): {e}"


def ask_claude(user_message):
    """Send message to Claude with tool use support — agentic loop."""
    global conversation_history

    conversation_history.append({"role": "user", "content": user_message})
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation_history
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    print(f"[tool] {block.name}({block.input}) → {str(result)[:80]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result)
                    })
            conversation_history.append({"role": "assistant", "content": response.content})
            conversation_history.append({"role": "user", "content": tool_results})

        else:
            reply = next((b.text for b in response.content if hasattr(b, "text")), "Done.")
            conversation_history.append({"role": "assistant", "content": reply})
            return reply


def handle_command(text):
    """Handle special /commands."""
    cmd = text.lower().strip()

    if cmd == "/start":
        return "👋 Hey Jaipal! I'm Bunty, your personal assistant. Ask me anything or use:\n\n/schedule — today's calendar\n/emails — check recent emails\n/help — show all commands"

    if cmd == "/schedule":
        summary = get_calendar_summary()
        from telegram_topics import send_daily
        send_daily(summary)
        return "📅 Calendar posted to Daily topic!"

    if cmd == "/emails":
        try:
            from email_bot import fetch_emails_since_dt, summarize_with_claude
            since_dt = _load_last_email_time()
            emails = fetch_emails_since_dt(since_dt)
            _save_last_email_time()
            if not emails:
                return "📭 No new emails since last check."
            return summarize_with_claude(emails)
        except Exception as e:
            return f"⚠️ Could not fetch emails: {e}"

    if cmd == "/stocks":
        try:
            subprocess.Popen(
                [PYTHON, str(STOCKS_DIR / "stock_alerts.py")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📊 Checking your stocks... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/jobs":
        try:
            return get_job_summary()
        except Exception as e:
            return f"⚠️ Could not fetch job alerts: {e}"

    if cmd.startswith("/post"):
        topic = text[5:].strip()
        if not topic:
            return "Usage: `/post your topic here`\nExample: `/post lessons learned from AWS certification`"
        try:
            success, post_text = post_from_topic(topic)
            if success:
                return f"✅ *Posted to LinkedIn!*\n\n{post_text}"
            else:
                return "⚠️ Post failed — check if Share on LinkedIn product is approved in your developer app."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/mystatus":
        try:
            return format_status_report()
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd.startswith("/update"):
        try:
            return handle_update_command(text)
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/findjobs":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "linkedin_apply.py"), "find"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔍 Searching LinkedIn for Easy Apply jobs matching your profile...\nResults will appear below — tap ✅ Apply or ❌ Skip on each one."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/findindeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "indeed_jobs.py"), "find"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔍 Searching Indeed for jobs in Dublin... results coming shortly!\nTap ✅ Apply or ❌ Skip on each one."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/applyindeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "indeed_jobs.py"), "apply"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🚀 Applying to approved Indeed jobs now... updates coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/login-indeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            subprocess.Popen(
                [python_exe, str(BASE / "indeed_jobs.py"), "login"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔐 Opening Indeed login browser on your PC...\nCredentials will be auto-filled. Complete any 2FA if prompted."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/autoapply-indeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "indeed_jobs.py"), "autoapply"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🤖 Indeed Auto Apply started — finding jobs and applying immediately, no approval needed!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/savedjobs-indeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "indeed_jobs.py"), "savedjobs"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔖 Applying to your Indeed Saved Jobs now... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/approveall-indeed":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "indeed_jobs.py"), "approveall"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "✅ Approving all pending Indeed jobs... then run /applyindeed to apply!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/feed":
        try:
            subprocess.Popen(
                [PYTHON, str(BASE / "linkedin_feed.py")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📰 Scanning your LinkedIn feed for quality posts... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/applyjobs":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "linkedin_apply.py"), "loginapply"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🚀 Applying to approved jobs now... results will arrive here shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/autoapply":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "linkedin_apply.py"), "autoapply"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🤖 Auto-applying to all new Easy Apply jobs — no approval needed! Updates coming shortly."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/savedjobs":
        try:
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            log_file = open(BASE / "bot.log", "a")
            subprocess.Popen(
                [python_exe, "-u", str(BASE / "linkedin_apply.py"), "savedjobs"],
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔖 Applying to your LinkedIn Saved Jobs now... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/login":
        try:
            # Use python.exe (not pythonw.exe) + CREATE_NEW_CONSOLE so
            # Playwright can open a visible browser window for login
            python_exe = PYTHON.replace("pythonw.exe", "python.exe").replace("pythonw", "python")
            subprocess.Popen(
                [python_exe, str(BASE / "fresh_login.py")],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return "🔐 Opening LinkedIn login browser on your PC...\nCredentials will be auto-filled. Complete any 2FA if prompted."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/resetfailed":
        try:
            from linkedin_apply import reset_failed_jobs
            n = reset_failed_jobs()
            if n:
                return f"🔄 Reset *{n} failed job(s)* back to approved. Run /applyjobs to retry them."
            return "✅ No failed jobs to reset."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/digest":
        try:
            subprocess.Popen(
                [PYTHON, str(BASE / "tech_digest.py")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📰 Fetching today's tech digest... posting to Daily shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/help":
        return (
            "/findjobs — find LinkedIn jobs\n"
            "/applyjobs — apply approved jobs\n"
            "/autoapply — find & apply now\n"
            "/savedjobs — apply saved jobs\n"
            "/login — LinkedIn login\n"
            "/resetfailed — retry failed\n"
            "/findindeed — find Indeed jobs\n"
            "/applyindeed — apply Indeed jobs\n"
            "/autoapply\\-indeed — Indeed auto apply\n"
            "/savedjobs\\-indeed — Indeed saved jobs\n"
            "/approveall\\-indeed — approve all Indeed\n"
            "/login\\-indeed — Indeed login\n"
            "/mystatus — application stats\n"
            "/update — update job stage\n"
            "/feed — LinkedIn feed\n"
            "/post — LinkedIn post\n"
            "/schedule — today's calendar\n"
            "/emails — Gmail summary\n"
            "/jobs — job alert emails\n"
            "/stocks — stock alerts\n"
            "/digest — tech news"
        )

    return None


def _load_last_email_time():
    try:
        if LAST_EMAIL_FILE.exists():
            dt = datetime.fromisoformat(LAST_EMAIL_FILE.read_text().strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        pass
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _save_last_email_time():
    LAST_EMAIL_FILE.write_text(datetime.now(timezone.utc).isoformat())


def startup_emails():
    """On startup, fetch and send new emails in a background thread (no window)."""
    def _run():
        try:
            from email_bot import fetch_emails_since_dt, summarize_with_claude
            from telegram_topics import send_chat
            since_dt = _load_last_email_time()
            emails = fetch_emails_since_dt(since_dt)
            _save_last_email_time()
            if emails:
                summary = summarize_with_claude(emails)
                send_chat(f"📬 *New emails since last check:*\n\n{summary}")
            else:
                send_chat("📭 No new emails since last check.")
        except Exception as e:
            print(f"Startup emails error: {e}")
    threading.Thread(target=_run, daemon=True).start()


def start_startup_login():
    """On bot start: check + auto-restore sessions in a background thread (no window)."""
    def _run():
        try:
            from startup_login import main as login_main
            asyncio.run(login_main())
        except Exception as e:
            print(f"Startup login error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    print(f"[{datetime.now().strftime('%H:%M')}] Startup login check launched.")


def start_linkedin_keepalive():
    """Keepalive loop in a background thread — no subprocess, no terminal window."""
    def _run():
        try:
            from linkedin_keepalive import keepalive_loop
            asyncio.run(keepalive_loop())
        except Exception as e:
            print(f"Keepalive error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    print(f"[{datetime.now().strftime('%H:%M')}] Keepalive daemon started.")


def run():
    print(f"[{datetime.now().strftime('%H:%M')}] Bot server started. Listening for messages...")
    send_message("🤖 Bunty is online! Type anything to chat, or use /help to see commands.")

    # Auto-login to LinkedIn + Indeed on every startup
    start_startup_login()

    # Start keepalive daemon — pings LinkedIn & Indeed every 30 min
    start_linkedin_keepalive()

    # Show new emails since last check
    startup_emails()

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                # Handle inline button taps
                if "callback_query" in update:
                    data = update.get("callback_query", {}).get("data", "")
                    try:
                        if data.startswith(("fc_", "fco_", "fs_")):
                            from linkedin_feed import handle_feed_callback
                            handle_feed_callback(update)
                        else:
                            from linkedin_apply import handle_callback
                            handle_callback(update)
                    except Exception as e:
                        print(f"Callback error: {e}")
                    continue

                msg       = update.get("message", {})
                text      = msg.get("text", "").strip()
                thread_id = msg.get("message_thread_id")

                if not text or not is_authorized(msg):
                    continue

                chat_id = msg.get("chat", {}).get("id", "?")
                chat_title = msg.get("chat", {}).get("title", "DM")
                print(f"[{datetime.now().strftime('%H:%M')}] chat={chat_id} ({chat_title}) thread={thread_id} | {text}")

                # Check for commands first
                if text.startswith("/"):
                    reply = handle_command(text)
                    if reply:
                        send_message(reply, thread_id=thread_id)
                        continue

                # Respond in any topic or DM
                try:
                    reply = ask_claude(text)
                    send_message(reply, thread_id=thread_id)
                except Exception as e:
                    send_message(f"⚠️ Error: {e}", thread_id=thread_id)

        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    run()
