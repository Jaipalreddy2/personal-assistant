#!/usr/bin/env python3
"""
Auto-login to LinkedIn and Indeed on system/bot startup.
Called by bot_server.py each time the bot starts.
Uses persistent Chrome profiles — if session is still valid, completes in seconds.
If expired, opens a visible browser, auto-fills credentials, waits for login.
"""
import asyncio
import sys
import io
from playwright.async_api import async_playwright

if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None and hasattr(sys.stderr, 'buffer') and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def send_telegram(msg):
    try:
        from telegram_topics import send_jobs
        send_jobs(msg)
    except Exception as e:
        print(f"Telegram error: {e}")


async def ensure_linkedin():
    from linkedin_browser import ensure_active_session
    print("Checking LinkedIn session...")
    async with async_playwright() as p:
        context, page = await ensure_active_session(p, send_telegram)
        if context is not None:
            print("LinkedIn: session active")
            await context.close()
            return True
        else:
            print("LinkedIn: login failed")
            return False


async def ensure_indeed():
    from indeed_jobs import ensure_indeed_session
    print("Checking Indeed session...")
    async with async_playwright() as p:
        context, page = await ensure_indeed_session(p, send_telegram)
        if context is not None:
            print("Indeed: session active")
            await context.close()
            return True
        else:
            print("Indeed: login failed")
            return False


async def main():
    send_telegram("🔄 Bunty starting — checking LinkedIn & Indeed sessions...")

    li_ok = await ensure_linkedin()
    indeed_ok = await ensure_indeed()

    if li_ok and indeed_ok:
        send_telegram("✅ LinkedIn & Indeed ready — bot fully online!")
    elif li_ok:
        send_telegram("✅ LinkedIn ready\n⚠️ Indeed login failed — run /login-indeed to fix")
    elif indeed_ok:
        send_telegram("✅ Indeed ready\n⚠️ LinkedIn login failed — run /login to fix")
    else:
        send_telegram("⚠️ Both sessions failed — run /login and /login-indeed")


if __name__ == "__main__":
    asyncio.run(main())
