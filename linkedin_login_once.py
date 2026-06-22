#!/usr/bin/env python3
"""Run this once to log into LinkedIn manually and save the session."""

import asyncio
import json
from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path

config = dotenv_values(Path.home() / ".env")
EMAIL    = config.get("LINKEDIN_EMAIL")
PASSWORD = config.get("LINKEDIN_PASSWORD")
SESSION  = Path(__file__).parent / "linkedin_session.json"


async def login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://www.linkedin.com/login")

        # Pre-fill credentials
        await page.wait_for_selector("#username", timeout=15000)
        await page.fill("#username", EMAIL)
        await page.fill("#password", PASSWORD)
        await page.click("button[type=submit]")
        await page.wait_for_timeout(3000)

        url = page.url
        if "checkpoint" in url or "challenge" in url:
            print("\n⚠️  LinkedIn requires verification.")
            print("Complete it in the browser window, then press Enter here...")
            input()
        elif "feed" in url:
            print("✅ Logged in automatically!")

        print("Saving session...")
        cookies = await page.context.cookies()
        SESSION.write_text(json.dumps({"cookies": cookies}))
        print(f"✅ Session saved to {SESSION}")
        print("You can close the browser now.")
        await page.wait_for_timeout(2000)
        await browser.close()


asyncio.run(login())
