#!/usr/bin/env python3
"""Retry failed jobs with VISIBLE browser so you can watch what's happening."""
import asyncio, random, sys, io
from pathlib import Path

if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if sys.stderr is not None and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from playwright.async_api import async_playwright
from linkedin_browser import get_context, is_logged_in
from linkedin_apply import init_db, update_job_status, apply_to_job, send_telegram, DB_PATH
import sqlite3

RETRY_IDS_FILE = Path(__file__).parent / "_retry_ids.txt"

async def main():
    init_db()

    ids = RETRY_IDS_FILE.read_text().strip().splitlines()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT id, title, company, location, url FROM jobs WHERE id IN ({','.join('?'*len(ids))})",
        ids
    ).fetchall()
    conn.close()
    jobs = [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4]} for r in rows]

    if not jobs:
        print("No jobs found to retry.")
        return

    print(f"Retrying {len(jobs)} jobs with VISIBLE browser...")

    async with async_playwright() as p:
        # headless=False so you can watch
        context = await get_context(p, headless=False)
        page = await context.new_page()

        # Navigate to feed first to warm up session cookies
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=30000)
        if not await is_logged_in(page):
            print("Not logged in — please log in manually in the browser")
            await asyncio.sleep(60)
        print("Logged in. Waiting 10s for cookies...")
        await page.wait_for_timeout(10000)

        applied = 0
        for i, job in enumerate(jobs, 1):
            print(f"\n[{i}/{len(jobs)}] {job['title']} @ {job['company']}")
            try:
                result = await apply_to_job(page, job)
                success, reason = result if isinstance(result, tuple) else (result, "")
            except Exception as e:
                success, reason = False, str(e)

            status = "applied" if success else "failed"
            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"Applied: *{job['title']}* @ {job['company']}")
                print(f"  Applied!")
            else:
                send_telegram(f"Could not apply: *{job['title']}* @ {job['company']} — {reason}")
                print(f"  Failed: {reason}")

            await asyncio.sleep(random.randint(8, 14))

        await context.close()

    send_telegram(f"Done! Applied *{applied}/{len(jobs)}*")
    print(f"\nFinished. Applied: {applied}/{len(jobs)}")

asyncio.run(main())
