#!/usr/bin/env python3
"""Test applying to a single job with full debug output."""
import sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
import linkedin_apply as la

# Pick one job from DB
import sqlite3
conn = sqlite3.connect("applied_jobs.db")
job_row = conn.execute(
    "SELECT id,title,company,location,url FROM jobs WHERE status='approved' LIMIT 1"
).fetchone()
conn.close()

if not job_row:
    print("No approved jobs in DB")
    sys.exit(0)

job = {"id": job_row[0], "title": job_row[1], "company": job_row[2],
       "location": job_row[3], "url": job_row[4]}
print(f"Testing job: {job['title']} @ {job['company']}")
print(f"URL: {job['url']}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,   # visible so we can see what's happening
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        loaded = await la.load_session(context)
        print(f"Session loaded: {loaded}")

        # Check session is valid
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"After /feed nav, URL: {page.url}")

        if "login" in page.url or "authwall" in page.url:
            print("SESSION EXPIRED — need to re-login first")
            await browser.close()
            return

        print("Session OK — navigating to job...")
        result = await la.apply_to_job(page, job)
        print(f"\nResult: {'APPLIED' if result else 'FAILED'}")

        await page.wait_for_timeout(3000)  # pause to observe result
        await browser.close()


asyncio.run(main())
