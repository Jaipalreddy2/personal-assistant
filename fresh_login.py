#!/usr/bin/env python3
"""
LinkedIn fresh login — saves session into the persistent Chrome profile.
Run this once. All future bot operations reuse the saved profile headlessly.
"""
import asyncio
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright
from linkedin_browser import get_context, is_logged_in, _autofill_login, PROFILE_DIR


async def fresh_login():
    print(f"Opening LinkedIn with persistent profile: {PROFILE_DIR}")
    async with async_playwright() as p:
        context = await get_context(p, headless=False)
        page = await context.new_page()

        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")

        # Check if already logged in
        await page.wait_for_timeout(2000)
        if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
            print("Already logged in! Session is active.")
            await context.close()
            return

        print("Attempting auto-fill...")
        submitted = await _autofill_login(page, print)
        if submitted:
            print("Credentials submitted — waiting for redirect...")

        # Wait up to 3 min
        try:
            await page.wait_for_url("**/feed**", timeout=180000)
        except Exception:
            pass

        if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
            print("Login successful! Session saved to persistent Chrome profile.")
            print("All future operations will run headlessly — no more popups.")
        else:
            print(f"Login may not have completed. Current URL: {page.url}")
            print("Please complete login manually in the browser window.")
            try:
                await page.wait_for_url("**/feed**", timeout=180000)
                print("Manual login detected — session saved!")
            except Exception:
                print("Timed out waiting for login.")

        await page.wait_for_timeout(2000)
        await context.close()


asyncio.run(fresh_login())
