#!/usr/bin/env python3
"""
Fresh LinkedIn login — no pre-loaded cookies, starts clean.
Opens a real visible browser. Log in manually if auto-fill fails.
"""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path

config   = dotenv_values(Path.home() / ".env")
EMAIL    = config.get("LINKEDIN_EMAIL")
PASSWORD = config.get("LINKEDIN_PASSWORD")
SESSION  = Path(__file__).parent / "linkedin_session.json"


async def fresh_login():
    async with async_playwright() as p:
        # Use a non-Chromium-default user agent and window size
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-IE",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        print("Opening LinkedIn login page (no pre-loaded cookies)...")
        try:
            await page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=30000
            )
        except Exception as e:
            print(f"Login page error: {e}")
            print("Trying linkedin.com homepage instead...")
            try:
                await page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                print(f"Homepage error: {e2}")

        await page.wait_for_timeout(3000)
        print(f"Current URL: {page.url}")

        # Try auto-fill — LinkedIn uses #username but may render slowly
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
            print(">>> Please log in manually in the browser window that just opened. <<<")
            print(">>> Waiting up to 3 minutes... <<<")

        # Wait up to 3 minutes for user to complete login / 2FA
        try:
            await page.wait_for_url("**/feed**", timeout=180000)
        except Exception:
            pass

        if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
            cookies = await context.cookies()
            SESSION.write_text(json.dumps({"cookies": cookies}))
            print(f"Session saved to {SESSION}")
            print("LinkedIn login successful!")
        else:
            print(f"Login may not have completed. URL: {page.url}")
            print("Saving whatever cookies we have...")
            cookies = await context.cookies()
            if cookies:
                SESSION.write_text(json.dumps({"cookies": cookies}))

        await page.wait_for_timeout(2000)
        await browser.close()


asyncio.run(fresh_login())
