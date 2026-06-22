#!/usr/bin/env python3
"""
Test which LinkedIn URL formats allow job page navigation.
Run this AFTER fresh_login.py so cookies are fresh.
"""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from pathlib import Path
from playwright.async_api import async_playwright

SESSION = Path(__file__).parent / "linkedin_session.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# A known DevOps job ID from our DB
TEST_JOB_ID = "4427485306"

URLS_TO_TEST = [
    f"https://www.linkedin.com/jobs/",
    f"https://www.linkedin.com/jobs/search/?keywords=devops+engineer&location=Dublin",
    f"https://www.linkedin.com/jobs/search/?keywords=devops&currentJobId={TEST_JOB_ID}",
    f"https://www.linkedin.com/jobs/view/{TEST_JOB_ID}/",
    f"https://www.linkedin.com/jobs/collections/recommended/",
]

async def test():
    data = json.loads(SESSION.read_text())
    cookies = data.get("cookies", data)
    for c in cookies:
        if c.get("domain", "").startswith(".www."):
            c["domain"] = c["domain"].replace(".www.", ".")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--start-maximized"]
        )
        ctx = await browser.new_context(
            user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-IE"
        )
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        # Step 1: Land on /feed first and wait for security cookies to refresh
        print("Step 1: Navigating to /feed...")
        try:
            await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=30000)
            print(f"  Landed: {page.url}")
            print("  Waiting 10s for security cookies to refresh...")
            await page.wait_for_timeout(10000)
        except Exception as e:
            print(f"  /feed failed: {e}")

        # Step 2: Try each URL
        for url in URLS_TO_TEST:
            print(f"\nTesting: {url[:70]}...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                print(f"  LANDED: {page.url[:80]}")
                print(f"  Title: {await page.title()}")
            except Exception as e:
                print(f"  FAILED: {e}")

        print("\nBrowser staying open for 15s...")
        await page.wait_for_timeout(15000)
        await browser.close()

asyncio.run(test())
