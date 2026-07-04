#!/usr/bin/env python3
"""
Real-time email monitor — started as background threads by bot_server.py.
1. startup_summary(): sends last 12h emails to Telegram Emails topic on bot start
2. monitor_loop():   polls every 60s for new emails, sends each one immediately
"""
import imaplib
import email
import json
import time
import threading
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import dotenv_values

config = dotenv_values(Path.home() / ".env")
GMAIL_ADDRESS  = config.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = config.get("GMAIL_APP_PASSWORD", "")
ANTHROPIC_KEY  = config.get("ANTHROPIC_API_KEY", "")

SEEN_FILE     = Path(__file__).parent / "seen_emails.json"
POLL_INTERVAL = 60  # seconds between checks


def _send(text):
    try:
        from telegram_topics import send_emails
        send_emails(text)
    except Exception as e:
        print(f"[email_monitor] Telegram error: {e}")


def _load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def _save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)[-2000:]))


def _fetch_since(since_dt):
    """Fetch all inbox emails received after since_dt."""
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
    mail.select("inbox")

    since_date = (since_dt - timedelta(days=1)).strftime("%d-%b-%Y")
    _, msg_ids = mail.search(None, f'(SINCE "{since_date}")')

    emails = []
    for mid in (msg_ids[0].split() if msg_ids[0] else []):
        try:
            _, data = mail.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            msg_id   = msg.get("Message-ID", str(mid))
            date_str = msg.get("Date", "")

            try:
                email_dt = parsedate_to_datetime(date_str)
                if email_dt.tzinfo is None:
                    email_dt = email_dt.replace(tzinfo=timezone.utc)
                if email_dt <= since_dt:
                    continue
            except Exception:
                pass

            subject_raw, enc = decode_header(msg["Subject"] or "No Subject")[0]
            subject = subject_raw.decode(enc or "utf-8") if isinstance(subject_raw, bytes) else (subject_raw or "No Subject")
            sender = msg.get("From", "Unknown")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass

            emails.append({
                "id":      msg_id,
                "subject": subject,
                "from":    sender,
                "date":    date_str,
                "body":    body[:1000],
            })
        except Exception:
            continue

    mail.logout()
    return emails


def _summarize_batch(emails):
    """Claude summary for a batch of emails (used on startup)."""
    try:
        import anthropic
        text = ""
        for i, e in enumerate(emails, 1):
            text += f"\n--- {i} ---\nFrom: {e['from']}\nSubject: {e['subject']}\n{e['body'][:400]}\n"
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content":
                f"Summarize these {len(emails)} emails briefly. For each: who it's from, what it's about, any action needed. Max 200 words.\n{text}"}]
        )
        return resp.content[0].text
    except Exception:
        lines = [f"• *{e['subject'][:60]}* — _{e['from'].split('<')[0].strip()[:30]}_" for e in emails[:10]]
        return "\n".join(lines)


def _format_single(e):
    """Format one new email as a Telegram message."""
    sender_name = e["from"].split("<")[0].strip().strip('"')[:40] or e["from"][:40]
    subject  = e["subject"][:80]
    snippet  = e["body"][:200].replace("\n", " ").strip()

    text_lower = (subject + " " + e["body"]).lower()
    if any(w in text_lower for w in ["interview", "phone screen", "video call", "schedule a"]):
        emoji = "🎯"
    elif any(w in text_lower for w in ["offer", "congratulations", "pleased to inform"]):
        emoji = "🎉"
    elif any(w in text_lower for w in ["unfortunately", "not moving forward", "other candidates"]):
        emoji = "❌"
    elif any(w in text_lower for w in ["recruiter", "recruiting", "talent acquisition", "opportunity"]):
        emoji = "👋"
    else:
        emoji = "📧"

    return (
        f"{emoji} *New Email*\n"
        f"*From:* {sender_name}\n"
        f"*Subject:* {subject}\n"
        f"_{snippet}_"
    )


def startup_summary():
    """Send summary of last 12h emails — called once on bot start."""
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        emails = _fetch_since(since)

        # Mark all as seen so monitor doesn't re-notify them
        seen = _load_seen()
        for e in emails:
            seen.add(e["id"])
        _save_seen(seen)

        if emails:
            summary = _summarize_batch(emails)
            _send(f"📬 *Emails — last 12 hours* ({len(emails)} unread)\n\n{summary}")
        else:
            _send("📭 No new emails in the last 12 hours.")

        print(f"[email_monitor] Startup summary: {len(emails)} emails")
    except Exception as ex:
        print(f"[email_monitor] Startup summary error: {ex}")


def monitor_loop():
    """Poll inbox every 60s. Send each new email to Telegram immediately."""
    seen       = _load_seen()
    last_check = datetime.now(timezone.utc)
    print(f"[email_monitor] Live monitor started — polling every {POLL_INTERVAL}s")

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            # Small overlap to avoid missing edge-case timing
            emails = _fetch_since(last_check - timedelta(seconds=10))
            last_check = datetime.now(timezone.utc)

            new_emails = [e for e in emails if e["id"] not in seen]
            for e in new_emails:
                seen.add(e["id"])
                _send(_format_single(e))
                print(f"[email_monitor] New email: {e['subject'][:50]}")

            if new_emails:
                _save_seen(seen)
        except Exception as ex:
            print(f"[email_monitor] Poll error: {ex}")


def start_in_background():
    """Launch startup summary + live monitor as daemon threads."""
    threading.Thread(target=startup_summary, daemon=True).start()
    threading.Thread(target=monitor_loop,    daemon=True).start()
