#!/usr/bin/env python3
"""
LinkedIn session keep-alive daemon.
Visits /feed every 30 minutes using the persistent Chrome profile so
LinkedIn never expires the session while the system is running.
Start this once at system boot (alongside bot_server.py).
"""
import asyncio
import sys
import io
from datetime import datetime
from playwright.async_api import async_playwright
from linkedin_browser import get_context, is_logged_in

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

INTERVAL = 30 * 60  # 30 minutes


async def keepalive_loop():
    ts = lambda: datetime.now().strftime("%H:%M")
    print(f"[{ts()}] LinkedIn keepalive started — pinging feed every 30 min.")
    while True:
        await asyncio.sleep(INTERVAL)
        try:
            async with async_playwright() as p:
                ctx = await get_context(p, headless=True)
                page = await ctx.new_page()
                active = await is_logged_in(page)
                await page.close()
                await ctx.close()
            status = "active" if active else "EXPIRED — run /login to refresh"
            print(f"[{ts()}] keepalive: LinkedIn session {status}")
        except Exception as e:
            print(f"[{ts()}] keepalive error: {e}")


asyncio.run(keepalive_loop())
