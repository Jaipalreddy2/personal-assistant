#!/usr/bin/env python3
"""
LinkedIn fresh login — saves session into the persistent Chrome profile.
Run this once to log in. All other scripts reuse the same profile
without needing to restore cookies (no fingerprint detection).
"""
import asyncio
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path
from linkedin_browser import get_context, PROFILE_DIR

config   = dotenv_values(Path.home() / ".env")
EMAIL    = config.get("LINKEDIN_EMAIL")
PASSWORD = config.get("LINKEDIN_PASSWORD")


async def fresh_login():
    print(f"Opening LinkedIn with persistent profile: {PROFILE_DIR}")
    async with async_playwright() as p:
        context = await get_context(p, headless=False)
        page = await context.new_page()

        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Login page error: {e}")

        await page.wait_for_timeout(3000)
        print(f"Current URL: {page.url}")

        if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
            print("Already logged in! Session is active.")
            await context.close()
            return

        # Try auto-fill
        try:
            await page.wait_for_selector("#username, input[name='session_key']", timeout=15000)
            email_sel = "#username" if await page.query_selector("#username") else "input[name='session_key']"
            pwd_sel   = "#password" if await page.query_selector("#password") else "input[name='session_password']"
            await page.fill(email_sel, EMAIL)
            await page.wait_for_timeout(600)
            await page.fill(pwd_sel, PASSWORD)
            await page.wait_for_timeout(600)
            await page.click("button[type='submit']")
            print("Credentials submitted, waiting for redirect...")
        except Exception as e:
            print(f"Auto-fill failed: {e}")
            print(">>> Please log in manually in the browser window. <<<")
            print(">>> Waiting up to 3 minutes... <<<")

        try:
            await page.wait_for_url("**/feed**", timeout=180000)
        except Exception:
            pass

        if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
            print("Login successful! Session saved to persistent Chrome profile.")
            print("All future operations will run headlessly — no more popups.")
        else:
            print(f"Login may not have completed. URL: {page.url}")

        await page.wait_for_timeout(2000)
        await context.close()


asyncio.run(fresh_login())
