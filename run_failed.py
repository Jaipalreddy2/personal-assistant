#!/usr/bin/env python3
"""
Retry all failed jobs with the fixed apply logic.
"""
import asyncio, random, sqlite3, sys, io
from pathlib import Path
from datetime import datetime

if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if sys.stderr is not None and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from playwright.async_api import async_playwright
from linkedin_browser import ensure_active_session, is_logged_in
from linkedin_apply import init_db, get_pending_jobs, update_job_status, apply_to_job, send_telegram, DB_PATH

# Jobs to retry (those just reset from failed)
RETRY_IDS_FILE = Path(__file__).parent / "_retry_ids.txt"

async def main():
    init_db()

    # Read the IDs we want to retry (written below before running)
    if RETRY_IDS_FILE.exists():
        ids = set(RETRY_IDS_FILE.read_text().strip().splitlines())
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            f"SELECT id, title, company, location, url FROM jobs WHERE id IN ({','.join('?'*len(ids))}) AND status='approved'",
            list(ids)
        ).fetchall()
        conn.close()
        jobs = [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4]} for r in rows]
    else:
        jobs = get_pending_jobs()

    if not jobs:
        print("No jobs to retry.")
        return

    print(f"Retrying {len(jobs)} jobs...")
    send_telegram(f"Retrying *{len(jobs)} failed jobs* with fixed apply logic...")

    async with async_playwright() as p:
        context, page = await ensure_active_session(p, send_telegram)
        if not await is_logged_in(page):
            send_telegram("LinkedIn session failed.")
            return

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

            await asyncio.sleep(random.randint(10, 18))

        await context.close()

    send_telegram(f"Done retrying! Applied *{applied}/{len(jobs)}*")
    print(f"\nFinished. Applied: {applied}/{len(jobs)}")

asyncio.run(main())
