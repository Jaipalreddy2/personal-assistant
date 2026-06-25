#!/usr/bin/env python3
"""
Login and apply in ONE continuous Playwright session — avoids PerimeterX
fingerprint mismatch that happens when cookies are saved/reloaded between sessions.

Usage:
    python run_apply.py
"""
import asyncio, json, random, sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright

# ── imports from existing modules ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from linkedin_apply import (
    init_db, get_pending_jobs, update_job_status,
    apply_to_job, send_telegram, load_session,
    find_and_connect_recruiter, DB_PATH
)
from resume_tailor import tailor_for_job

config  = dotenv_values(Path.home() / ".env")
EMAIL   = config.get("LINKEDIN_EMAIL", "")
PASSWD  = config.get("LINKEDIN_PASSWORD", "")
SESSION = Path(__file__).parent / "linkedin_session.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


async def ensure_logged_in(page, context):
    """Navigate to /feed; if not logged in, do visible login and wait."""
    try:
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  /feed nav error: {e}")

    await page.wait_for_timeout(5000)

    if "feed" in page.url:
        print(f"Already logged in: {page.url}")
        return True

    # Not on feed → show login page
    print("Not logged in — navigating to login page...")
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    # Try auto-fill
    if EMAIL and PASSWD:
        try:
            await page.wait_for_selector("#username", timeout=6000)
            await page.fill("#username", EMAIL)
            await page.wait_for_timeout(500)
            await page.fill("#password", PASSWD)
            await page.wait_for_timeout(500)
            await page.click("button[type='submit']")
            print("Credentials submitted — waiting for feed...")
        except Exception:
            print("Auto-fill failed — please log in manually in the browser window.")

    # Wait up to 3 minutes for manual/2FA completion
    try:
        await page.wait_for_url("**/feed**", timeout=180000)
    except Exception:
        pass

    if "feed" not in page.url:
        print(f"Login did not complete. Current URL: {page.url}")
        return False

    # Save fresh cookies for future use
    cookies = await context.cookies()
    SESSION.write_text(json.dumps({"cookies": cookies}))
    print(f"Session saved ({len(cookies)} cookies)")
    return True


async def main():
    init_db()
    approved = get_pending_jobs()

    if not approved:
        print("No approved jobs to apply to.")
        send_telegram("📋 No approved jobs to apply to. Use /findjobs and approve some first.")
        return

    print(f"Found {len(approved)} approved jobs.")
    send_telegram(f"🚀 Applying to *{len(approved)} approved jobs*...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        context = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="en-IE",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = await context.new_page()

        # Try loading saved session first (avoids manual login if cookies still valid)
        session_loaded = False
        if SESSION.exists():
            try:
                await load_session(context)
                session_loaded = True
                print("Loaded saved session cookies.")
            except Exception as e:
                print(f"Could not load session: {e}")

        ok = await ensure_logged_in(page, context)
        if not ok:
            send_telegram("❌ LinkedIn login failed — please try again.")
            await browser.close()
            return

        # Let the page fully settle and refresh security cookies
        print("Feed loaded — waiting 10s for security cookies to refresh...")
        await page.wait_for_timeout(10000)

        applied = 0
        for i, job in enumerate(approved, 1):
            print(f"\n[{i}/{len(approved)}] {job['title']} @ {job['company']}")

            # Tailor resume
            try:
                tailored = await tailor_for_job(job, page=page)
                if tailored:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE jobs SET tailored_resume=? WHERE id=?", (tailored, job["id"]))
                    conn.commit()
                    conn.close()
            except Exception as e:
                print(f"  Tailor error: {e}")

            # Apply
            try:
                success, reason = await apply_to_job(page, job)
                status = "applied" if success else "failed"
            except Exception as e:
                reason = str(e)
                status = "failed"
                success = False

            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"✅ Applied: *{job['title']}* at {job['company']}")
                # Recruiter outreach
                try:
                    await find_and_connect_recruiter(page, job)
                except Exception:
                    pass
            else:
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

            delay = random.randint(12, 22)
            print(f"  Sleeping {delay}s before next job...")
            await asyncio.sleep(delay)

        await browser.close()

    send_telegram(f"🎉 Done! Applied to *{applied}/{len(approved)}* jobs.")
    print(f"\nDone. Applied: {applied}/{len(approved)}")


if __name__ == "__main__":
    asyncio.run(main())
