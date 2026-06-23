#!/usr/bin/env python3
"""
Indeed Job Search + Apply Bot
- Finds jobs via Indeed RSS (no login required for search)
- Sends to Telegram for approval (same ✅/❌ buttons as LinkedIn)
- Applies via Playwright using a persistent Chrome profile
"""

import asyncio
import sys
import io
import json
import random
import sqlite3
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from dotenv import dotenv_values
from playwright.async_api import async_playwright

if sys.stdout is not None and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

config = dotenv_values(Path.home() / ".env")

INDEED_EMAIL    = config.get("INDEED_EMAIL", "")
INDEED_PASSWORD = config.get("INDEED_PASSWORD", "")
PHONE_NUMBER    = config.get("PHONE", "+353870042809")
RESUME_PDF      = Path(__file__).parent / "Jaipal_Kasi_Reddy_Resume.pdf"
DB_PATH         = Path(__file__).parent / "applied_jobs.db"
PROFILE_DIR     = str(Path(__file__).parent / "indeed_chrome_profile")

LOCATION = "Dublin, Ireland"

JOB_KEYWORDS = [
    "Junior DevOps Engineer",
    "Graduate DevOps Engineer",
    "Junior Cloud Engineer",
    "Graduate Software Engineer",
    "Junior Software Engineer",
    "Entry Level DevOps",
    "Cloud Engineer",
    "Junior Python Developer",
    "Junior Platform Engineer",
    "Associate DevOps Engineer",
    "Junior AWS Engineer",
    "Junior Site Reliability Engineer",
]

SENIOR_KEYWORDS = [
    "senior", "lead", "principal", "staff", "head of", "director",
    "manager", "architect", "vp ", "vice president", "5+ years",
    "7+ years", "8+ years", "10+ years",
]

TECH_KEYWORDS = [
    "engineer", "developer", "devops", "cloud", "platform", "software",
    "infrastructure", "sre", "reliability", "python", "aws", "kubernetes",
    "docker", "backend", "fullstack", "full stack", "full-stack",
    "it ", "data", "systems", "network", "security", "technical", "computing",
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-infobars",
]


# ── Database ───────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            title           TEXT,
            company         TEXT,
            location        TEXT,
            url             TEXT,
            status          TEXT DEFAULT 'pending',
            stage           TEXT DEFAULT 'pending',
            notes           TEXT,
            tailored_resume TEXT,
            recruiter       TEXT,
            found_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            applied_at      DATETIME,
            source          TEXT DEFAULT 'linkedin'
        )
    """)
    for col, definition in [
        ("stage",           "TEXT DEFAULT 'pending'"),
        ("notes",           "TEXT"),
        ("tailored_resume", "TEXT"),
        ("recruiter",       "TEXT"),
        ("source",          "TEXT DEFAULT 'linkedin'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {definition}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_job(job):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO jobs (id, title, company, location, url, source) VALUES (?,?,?,?,?,?)",
            (job["id"], job["title"], job["company"], job["location"], job["url"], job.get("source", "indeed")),
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def already_seen(job_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return row is not None


def update_job_status(job_id, status):
    conn = sqlite3.connect(DB_PATH)
    if status == "applied":
        conn.execute(
            "UPDATE jobs SET status=?, stage=?, applied_at=? WHERE id=?",
            (status, "applied", datetime.now().isoformat(), job_id),
        )
    else:
        conn.execute(
            "UPDATE jobs SET status=?, applied_at=? WHERE id=?",
            (status, datetime.now().isoformat(), job_id),
        )
    conn.commit()
    conn.close()


def get_approved_indeed_jobs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, title, company, location, url FROM jobs WHERE status='approved' AND source='indeed'"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4]} for r in rows]


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(text, reply_markup=None):
    from telegram_topics import TOPICS, GROUP_ID, TOKEN as TG_TOKEN
    payload = {
        "chat_id": GROUP_ID,
        "text": text,
        "parse_mode": "Markdown",
        "message_thread_id": TOPICS["jobs"],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"  Telegram error: {e}")


def send_job_for_approval(job):
    markup = {
        "inline_keyboard": [[
            {"text": "✅ Apply", "callback_data": f"apply_{job['id']}"},
            {"text": "❌ Skip",  "callback_data": f"skip_{job['id']}"},
        ]]
    }
    text = (
        f"🔍 *Indeed Job Found*\n\n"
        f"*{job['title']}*\n"
        f"🏢 {job['company']}\n"
        f"📍 {job['location']}\n\n"
        f"[View on Indeed]({job['url']})"
    )
    send_telegram(text, reply_markup=markup)


# ── Job search via Playwright ──────────────────────────────────────────────────

def _is_relevant(title):
    t = title.lower()
    if any(kw in t for kw in SENIOR_KEYWORDS):
        return False
    if not any(kw in t for kw in TECH_KEYWORDS):
        return False
    return True


async def scrape_indeed_keyword(page, keyword, days=14):
    """Scrape Indeed search results for one keyword. Returns list of job dicts."""
    params = urlencode({"q": keyword, "l": LOCATION, "sort": "date", "fromage": str(days)})
    url = f"https://ie.indeed.com/jobs?{params}"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  Nav error for '{keyword}': {e}")
        return []

    await page.wait_for_timeout(3000)

    # Dismiss cookie banner if present
    try:
        await page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const t = (btn.innerText || '').trim().toLowerCase();
                if (t === 'accept' || t === 'accept all' || t === 'i accept') { btn.click(); return; }
            }
        }""")
        await page.wait_for_timeout(800)
    except Exception:
        pass

    await page.wait_for_timeout(1500)

    jobs = await page.evaluate("""() => {
        const results = [];
        // data-jk is on the <a> job title link; parent <li> has company/location
        const jobLinks = document.querySelectorAll('a[data-jk]');
        for (const link of jobLinks) {
            try {
                const jk = link.getAttribute('data-jk');
                if (!jk) continue;

                // Title is in span[title] inside the link
                const titleEl = link.querySelector('span[title]') || link.querySelector('span');
                const title = titleEl ? (titleEl.getAttribute('title') || titleEl.innerText || '').trim() : '';
                if (!title) continue;

                const li = link.closest('li');
                if (!li) continue;

                const compEl = li.querySelector('[data-testid="company-name"]');
                const company = compEl ? compEl.innerText.trim() : 'Unknown';

                const locEl = li.querySelector('[data-testid="text-location"]');
                const location = locEl ? locEl.innerText.trim() : 'Dublin, Ireland';

                results.push({
                    id: 'indeed_' + jk,
                    title: title,
                    company: company,
                    location: location.split('\\n')[0].trim(),
                    url: 'https://ie.indeed.com/viewjob?jk=' + jk,
                    source: 'indeed',
                });
            } catch(e) {}
        }
        return results;
    }""")

    print(f"  Found {len(jobs)} cards for '{keyword}'")
    return jobs


async def find_jobs():
    """Search all keywords via Playwright, save new jobs, send to Telegram for approval."""
    init_db()
    all_new = []
    seen_this_run = set()

    async with async_playwright() as p:
        # Use persistent profile so Indeed sees a real browser fingerprint
        context = await get_indeed_context(p, headless=True)
        page = await context.new_page()

        for kw in JOB_KEYWORDS:
            print(f"Searching Indeed: {kw}")
            jobs = await scrape_indeed_keyword(page, kw)
            for job in jobs:
                if job["id"] in seen_this_run:
                    continue
                seen_this_run.add(job["id"])
                if already_seen(job["id"]):
                    continue
                if not _is_relevant(job["title"]):
                    print(f"  Skipping: {job['title']}")
                    continue
                save_job(job)
                all_new.append(job)
            await asyncio.sleep(random.randint(2, 4))

        await context.close()

    if not all_new:
        send_telegram("🔍 *Indeed Search*: No new jobs found this time.")
        print("No new Indeed jobs found.")
        return

    send_telegram(f"🔍 *Indeed Search*: Found *{len(all_new)} new jobs!* Sending for approval...")
    for job in all_new:
        send_job_for_approval(job)
        await asyncio.sleep(0.5)

    print(f"Done. Found {len(all_new)} new Indeed jobs.")


# ── Indeed Browser (persistent Chrome profile) ─────────────────────────────────

async def get_indeed_context(playwright, headless=True):
    return await playwright.chromium.launch_persistent_context(
        PROFILE_DIR,
        channel="chrome",
        headless=headless,
        args=_ARGS,
        viewport={"width": 1366, "height": 768},
        user_agent=_UA,
        locale="en-IE",
    )


async def is_logged_in_indeed(page):
    try:
        await page.goto("https://ie.indeed.com/", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        # "Sign in" link present = not logged in
        sign_in = await page.query_selector(
            "a[href*='account/login'], a[data-tn-element*='signin'], button[data-tn-component*='signin']"
        )
        # If we can see the user nav or profile, we're in
        logged_in_el = await page.query_selector(
            "a[href*='myjobs'], a[href*='profile'], div[data-tn-component*='account']"
        )
        return sign_in is None or logged_in_el is not None
    except Exception:
        return False


async def ensure_indeed_session(playwright, send_fn):
    """Return (context, page) logged into Indeed. Opens visible browser if session expired."""
    context = await get_indeed_context(playwright, headless=True)
    page = await context.new_page()
    if await is_logged_in_indeed(page):
        return context, page

    await page.close()
    await context.close()
    send_fn("🔐 Indeed session expired — opening browser to sign in...")

    context = await get_indeed_context(playwright, headless=False)
    page = await context.new_page()

    try:
        await page.goto("https://ie.indeed.com/account/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Fill email
        for sel in ["input[name='__email']", "#login-email-input", "input[type='email']"]:
            try:
                await page.wait_for_selector(sel, state="visible", timeout=5000)
                await page.fill(sel, INDEED_EMAIL)
                break
            except Exception:
                continue

        await page.wait_for_timeout(500)

        # Click Continue/Next to reveal password field
        for sel in ["button[type='submit']", "#login-submit-button", "button[data-tn-element*='continue']"]:
            try:
                await page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        await page.wait_for_timeout(1500)

        # Fill password
        for sel in ["input[name='__password']", "#login-password-input", "input[type='password']"]:
            try:
                await page.wait_for_selector(sel, state="visible", timeout=8000)
                await page.fill(sel, INDEED_PASSWORD)
                break
            except Exception:
                continue

        await page.wait_for_timeout(500)

        # Submit
        for sel in ["button[type='submit']", "#login-submit-button"]:
            try:
                await page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        send_fn("⏳ Credentials submitted — waiting for Indeed to load (up to 3 min)...")
    except Exception as e:
        send_fn(f"⚠️ Auto-fill issue: {e} — please log in manually in the browser window.")

    try:
        await page.wait_for_url("*ie.indeed.com/**", timeout=180000)
    except Exception:
        pass

    if await is_logged_in_indeed(page):
        send_fn("✅ Indeed logged in! Continuing...")
        return context, page

    send_fn("⚠️ Waiting for 2FA/CAPTCHA completion — 3 more minutes...")
    try:
        await asyncio.sleep(180)
    except Exception:
        pass

    if await is_logged_in_indeed(page):
        send_fn("✅ Indeed logged in!")
        return context, page

    await context.close()
    send_fn("❌ Indeed login timed out. Run /login-indeed and sign in manually.")
    return None, None


async def _upload_resume(page):
    if not RESUME_PDF.exists():
        return
    try:
        file_inputs = await page.query_selector_all("input[type='file']")
        for fi in file_inputs:
            try:
                await fi.set_input_files(str(RESUME_PDF))
                await page.wait_for_timeout(1000)
                print("  Uploaded resume")
                return
            except Exception:
                continue
    except Exception:
        pass


async def apply_to_indeed_job(page, job):
    """Navigate to job and attempt Indeed Easy Apply. Returns True on success."""
    try:
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000 + random.randint(500, 1500))

        # Find the apply button
        apply_btn = None
        for sel in [
            "button[id*='apply-button']",
            "button[data-tn-element='jobsearch-IndeedApplyButton']",
            "button.ia-IndeedApplyButton",
            "span.indeed-apply-widget button",
            "a[href*='applystart']",
            "#applyButton",
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    apply_btn = el
                    break
            except Exception:
                continue

        if not apply_btn:
            # Fallback: search by button text
            handle = await page.evaluate_handle("""() => {
                for (const el of document.querySelectorAll('button, a')) {
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (t === 'apply now' || t === 'easily apply' || t.startsWith('apply now') || t === 'apply') {
                        return el;
                    }
                }
                return null;
            }""")
            try:
                if not await handle.evaluate("el => el === null"):
                    apply_btn = handle
            except Exception:
                pass

        if not apply_btn:
            send_telegram(f"⚠️ No apply button — apply manually:\n{job['url']}")
            return False

        try:
            await apply_btn.scroll_into_view_if_needed()
            await apply_btn.click()
        except Exception:
            await page.evaluate("el => el.click()", apply_btn)

        await page.wait_for_timeout(3000)

        # If redirected away from Indeed, it's an external application
        if "indeed.com" not in page.url:
            send_telegram(f"🌐 External apply for *{job['title']}*:\n{page.url}")
            return False

        # Upload resume if prompted
        await _upload_resume(page)

        # Fill basic personal info fields
        try:
            for sel in ["input[name*='name'][type='text']", "input[id*='applicant-name']"]:
                el = await page.query_selector(sel)
                if el and not await el.input_value():
                    await el.fill("Jaipal Kasi Reddy")
                    break
        except Exception:
            pass

        try:
            for sel in ["input[type='tel']", "input[name*='phone']", "input[id*='phone']"]:
                el = await page.query_selector(sel)
                if el and not await el.input_value():
                    await el.fill(PHONE_NUMBER)
                    break
        except Exception:
            pass

        # Step through multi-page form (up to 8 steps)
        for _ in range(8):
            await page.wait_for_timeout(1500)

            # Success indicators
            success = await page.query_selector(
                "h1[class*='success'], [data-tn-component*='applicationSubmitted'], "
                "[class*='confirmation'], h2[class*='thank']"
            )
            if success or "apply/confirmation" in page.url or "thankyou" in page.url.lower():
                return True

            # Submit button
            submit_btn = None
            for sel in [
                "button[data-tn-element='submit-button']",
                "button[aria-label*='ubmit']",
                "button[type='submit']",
            ]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        t = (await el.inner_text()).strip().lower()
                        if "submit" in t:
                            submit_btn = el
                            break
                except Exception:
                    continue

            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(3000)
                return True  # optimistic after submit click

            # Continue / Next button
            next_btn = None
            for sel in [
                "button[data-tn-element='continue-button']",
                "button[aria-label*='ontinue']",
                "button[aria-label*='ext step']",
            ]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        next_btn = el
                        break
                except Exception:
                    continue

            if not next_btn:
                # Try by text
                handle = await page.evaluate_handle("""() => {
                    for (const btn of document.querySelectorAll('button')) {
                        const t = (btn.innerText || '').trim().toLowerCase();
                        if (['continue', 'next', 'save and continue', 'next step'].includes(t))
                            return btn;
                    }
                    return null;
                }""")
                try:
                    if not await handle.evaluate("el => el === null"):
                        next_btn = handle
                except Exception:
                    pass

            if next_btn:
                await next_btn.click()
            else:
                break  # no more buttons — end of form

        return False

    except Exception as e:
        print(f"  Indeed apply error for {job['title']}: {e}")
        return False


async def apply_approved():
    """Apply to all Indeed-approved jobs using the persistent Chrome profile."""
    init_db()
    approved = get_approved_indeed_jobs()
    if not approved:
        send_telegram("📋 No approved Indeed jobs to apply to. Run /findindeed first, then approve jobs.")
        return

    async with async_playwright() as p:
        context, page = await ensure_indeed_session(p, send_telegram)
        if context is None:
            return

        send_telegram(f"✅ Indeed active — applying to *{len(approved)} jobs* now...")

        applied = 0
        for job in approved:
            try:
                success = await apply_to_indeed_job(page, job)
                status  = "applied" if success else "failed"
            except Exception as e:
                print(f"  Error: {e}")
                status  = "failed"
                success = False

            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"✅ Applied (Indeed): *{job['title']}* at {job['company']}")
            else:
                send_telegram(f"⚠️ Could not apply: *{job['title']}* at {job['company']}")

            await asyncio.sleep(random.randint(8, 15))

        await context.close()

    send_telegram(f"🎉 Done! Applied to *{applied}/{len(approved)}* Indeed jobs.")


async def login_indeed_visible():
    """Open the Indeed Chrome profile visibly for a one-time login."""
    send_telegram("🔐 Opening Indeed login browser — credentials will be auto-filled.")
    async with async_playwright() as p:
        context = await get_indeed_context(p, headless=False)
        page = await context.new_page()
        try:
            await page.goto("https://ie.indeed.com/account/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            if await is_logged_in_indeed(page):
                send_telegram("✅ Already logged into Indeed!")
                return

            for sel in ["input[name='__email']", "#login-email-input", "input[type='email']"]:
                try:
                    await page.wait_for_selector(sel, state="visible", timeout=5000)
                    await page.fill(sel, INDEED_EMAIL)
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(500)

            for sel in ["button[type='submit']", "#login-submit-button"]:
                try:
                    await page.click(sel, timeout=3000)
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(1500)

            for sel in ["input[name='__password']", "#login-password-input", "input[type='password']"]:
                try:
                    await page.wait_for_selector(sel, state="visible", timeout=8000)
                    await page.fill(sel, INDEED_PASSWORD)
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(500)

            for sel in ["button[type='submit']", "#login-submit-button"]:
                try:
                    await page.click(sel, timeout=3000)
                    break
                except Exception:
                    continue

            send_telegram("⏳ Waiting for Indeed login (up to 5 min — complete 2FA if needed)...")
            try:
                await page.wait_for_url("*ie.indeed.com/**", timeout=300000)
            except Exception:
                pass

            if await is_logged_in_indeed(page):
                send_telegram("✅ Indeed logged in! Session saved.")
            else:
                send_telegram("❌ Login may not have completed. Try again or log in manually.")
        finally:
            await context.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    if cmd == "find":
        asyncio.run(find_jobs())
    elif cmd == "apply":
        asyncio.run(apply_approved())
    elif cmd == "login":
        asyncio.run(login_indeed_visible())
