#!/usr/bin/env python3
"""Retry the last failed job."""
import asyncio
import sqlite3
import sys
import io
from pathlib import Path

if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if sys.stderr is not None and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from playwright.async_api import async_playwright
from linkedin_browser import ensure_active_session, is_logged_in
from linkedin_apply import init_db, update_job_status, apply_to_job, send_telegram, DB_PATH

async def main():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    # Get the last failed job
    row = conn.execute(
        "SELECT id, title, company, location, url FROM jobs WHERE status='failed' ORDER BY applied_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        print("No failed jobs found.")
        return

    job = {"id": row[0], "title": row[1], "company": row[2], "location": row[3], "url": row[4]}
    print(f"Retrying: {job['title']} @ {job['company']}")
    send_telegram(f"Retrying: *{job['title']}* @ {job['company']}...")

    # Reset to approved so it can be applied
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='approved' WHERE id=?", (job["id"],))
    conn.commit()
    conn.close()

    async with async_playwright() as p:
        context, page = await ensure_active_session(p, send_telegram)
        if not await is_logged_in(page):
            print("LinkedIn session failed.")
            return

        print("Logged in. Waiting 10s for cookies...")
        await page.wait_for_timeout(10000)

        result = await apply_to_job(page, job)
        if isinstance(result, tuple):
            success, reason = result
        else:
            success, reason = result, ""

        status = "applied" if success else "failed"
        update_job_status(job["id"], status)

        if success:
            send_telegram(f"Applied: *{job['title']}* @ {job['company']}")
            print(f"Applied successfully!")
        else:
            send_telegram(f"Failed: *{job['title']}* @ {job['company']} — {reason}")
            print(f"Failed: {reason}")

        await context.close()

asyncio.run(main())
