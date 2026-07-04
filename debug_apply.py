"""Run apply for the last 2 failed LinkedIn jobs with browser visible."""
import asyncio
import sqlite3
import random
from pathlib import Path
from playwright.async_api import async_playwright

DB_PATH = Path(__file__).parent / "applied_jobs.db"
JOB_IDS = [
    "4433804009",  # Software Engineer, Zetheta Algorithms
    "4302189675",  # Graduate Electrical Engineer, Arup
    "4431463149",  # Security Engineer - Incident Response, Squarespace
    "4426060163",  # Business Control Unit Intern, NBC Global Finance
]


def reset_to_approved():
    conn = sqlite3.connect(DB_PATH)
    for jid in JOB_IDS:
        conn.execute("UPDATE jobs SET status='approved' WHERE id=?", (jid,))
    conn.commit()
    conn.close()
    print("Reset jobs to approved.")


def update_status(job_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    conn.commit()
    conn.close()


async def main():
    reset_to_approved()

    # Fetch jobs
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(JOB_IDS))
    jobs = conn.execute(
        f"SELECT * FROM jobs WHERE id IN ({placeholders})", JOB_IDS
    ).fetchall()
    conn.close()
    jobs = [dict(j) for j in jobs]
    print(f"Applying to {len(jobs)} jobs with VISIBLE browser...")

    from linkedin_browser import get_context, is_logged_in
    from linkedin_apply import apply_to_job, dismiss_cookie_banner

    async with async_playwright() as p:
        # Force headless=False so you can see what happens
        context = await get_context(p, headless=False)
        page = await context.new_page()

        logged_in = await is_logged_in(page)
        print(f"LinkedIn logged in: {logged_in}")
        if not logged_in:
            print("Not logged in — navigate to linkedin.com and log in manually, then press Enter.")
            input()

        for job in jobs:
            print(f"\n--- Applying: {job['title']} @ {job['company']} ---")
            success, reason = await apply_to_job(page, job)
            status = "applied" if success else "failed"
            update_status(job["id"], status)
            if success:
                print(f"  ✅ Applied!")
            else:
                print(f"  ❌ Failed — Reason: {reason}")
            await asyncio.sleep(random.randint(5, 10))

        input("\nDone. Press Enter to close the browser.")
        await context.close()


asyncio.run(main())
