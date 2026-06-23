#!/usr/bin/env python3
"""
Session keep-alive daemon for LinkedIn and Indeed.
Pings both sites every 30 minutes so sessions never expire while the system is on.
Also auto-restores expired sessions using saved credentials.
"""
import asyncio
import sys
import io
from datetime import datetime
from playwright.async_api import async_playwright
from linkedin_browser import get_context, is_logged_in, ensure_active_session

if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None and hasattr(sys.stderr, 'buffer') and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

INTERVAL = 30 * 60  # 30 minutes


def send_telegram(msg):
    try:
        from telegram_topics import send_jobs
        send_jobs(msg)
    except Exception:
        pass


def ts():
    return datetime.now().strftime("%H:%M")


async def ping_linkedin():
    try:
        async with async_playwright() as p:
            ctx = await get_context(p, headless=True)
            page = await ctx.new_page()
            active = await is_logged_in(page)
            await page.close()
            await ctx.close()

        if active:
            print(f"[{ts()}] LinkedIn: session active")
        else:
            print(f"[{ts()}] LinkedIn: session expired — attempting auto-login...")
            async with async_playwright() as p:
                context, page = await ensure_active_session(p, send_telegram)
                if context:
                    await context.close()
                    print(f"[{ts()}] LinkedIn: re-login successful")
                else:
                    print(f"[{ts()}] LinkedIn: re-login failed")
    except Exception as e:
        print(f"[{ts()}] LinkedIn keepalive error: {e}")


async def ping_indeed():
    try:
        from indeed_jobs import get_indeed_context, is_logged_in_indeed, ensure_indeed_session
        async with async_playwright() as p:
            ctx = await get_indeed_context(p, headless=True)
            page = await ctx.new_page()
            active = await is_logged_in_indeed(page)
            await page.close()
            await ctx.close()

        if active:
            print(f"[{ts()}] Indeed: session active")
        else:
            print(f"[{ts()}] Indeed: session expired — attempting auto-login...")
            async with async_playwright() as p:
                context, page = await ensure_indeed_session(p, send_telegram)
                if context:
                    await context.close()
                    print(f"[{ts()}] Indeed: re-login successful")
                else:
                    print(f"[{ts()}] Indeed: re-login failed")
    except Exception as e:
        print(f"[{ts()}] Indeed keepalive error: {e}")


async def keepalive_loop():
    print(f"[{ts()}] Keepalive started — pinging LinkedIn & Indeed every 30 min.")
    while True:
        await asyncio.sleep(INTERVAL)
        await ping_linkedin()
        await asyncio.sleep(5)
        await ping_indeed()


if __name__ == "__main__":
    asyncio.run(keepalive_loop())
