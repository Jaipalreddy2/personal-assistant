#!/usr/bin/env python3
"""
LinkedIn Easy Apply Bot
- Finds Easy Apply jobs matching Jaipal's profile
- Sends job details to Telegram for approval
- Applies to approved jobs automatically
"""

import asyncio
import json
import random
import sqlite3
import requests
import time
import sys
import io
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright

# Force UTF-8 output on Windows to support emoji in print statements
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

config = dotenv_values(Path.home() / ".env")

TELEGRAM_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = config.get("TELEGRAM_CHAT_ID")
TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

JOB_KEYWORDS = [
    "Junior DevOps Engineer",
    "Graduate DevOps Engineer",
    "Junior Cloud Engineer",
    "Graduate Software Engineer",
    "Junior Software Engineer",
    "Entry Level DevOps",
    "Graduate Cloud Engineer",
    "Junior Platform Engineer",
    "Associate DevOps Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Junior AWS Engineer",
    "Graduate Cloud Computing",
    "Junior Python Developer",
    "Cloud Infrastructure Engineer",
    "Junior Kubernetes Engineer",
    "Graduate IT Engineer",
    "Junior Site Reliability Engineer",
]

# Keywords that indicate a role is suitable for freshers/graduates
FRESHER_KEYWORDS = [
    "junior", "graduate", "entry level", "entry-level", "fresher",
    "associate", "trainee", "apprentice", "0-2 years", "0-1 year",
    "1-2 years", "new grad", "recent graduate", "no experience required",
    "early career",
]

# Keywords that indicate a senior role — skip these
SENIOR_KEYWORDS = [
    "senior", "lead", "principal", "staff", "head of", "director",
    "manager", "architect", "vp ", "vice president", "5+ years",
    "7+ years", "8+ years", "10+ years",
]


def is_fresher_role(title):
    """Return True if the job title looks suitable for a fresher/graduate."""
    title_lower = title.lower()
    # Skip if clearly senior
    if any(kw in title_lower for kw in SENIOR_KEYWORDS):
        return False
    # Auto-approve if explicitly junior/graduate
    if any(kw in title_lower for kw in FRESHER_KEYWORDS):
        return True
    # Accept generic titles like "DevOps Engineer", "Cloud Engineer" (no level specified)
    return True

LINKEDIN_EMAIL    = config.get("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = config.get("LINKEDIN_PASSWORD")

LOCATION     = "Dublin, Ireland"
DB_PATH      = Path(__file__).parent / "applied_jobs.db"
SESSION_FILE = Path(__file__).parent / "linkedin_session.json"
RESUME_PDF   = Path(__file__).parent / "Jaipal_Kasi_Reddy_Resume.pdf"


# ── Database ──────────────────────────────────────────────────────────────────

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
            applied_at      DATETIME
        )
    """)
    # Add columns if upgrading from older schema
    for col, definition in [
        ("stage",           "TEXT DEFAULT 'pending'"),
        ("notes",           "TEXT"),
        ("tailored_resume", "TEXT"),
        ("recruiter",       "TEXT"),
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
            "INSERT OR IGNORE INTO jobs (id, title, company, location, url) VALUES (?,?,?,?,?)",
            (job["id"], job["title"], job["company"], job["location"], job["url"])
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def update_job_status(job_id, status):
    conn = sqlite3.connect(DB_PATH)
    # Only advance stage to 'applied' on confirmed success
    # For failed/skipped/approved, keep stage as-is so tracker stays clean
    if status == "applied":
        conn.execute(
            "UPDATE jobs SET status=?, stage=?, applied_at=? WHERE id=?",
            (status, "applied", datetime.now().isoformat(), job_id)
        )
    else:
        conn.execute(
            "UPDATE jobs SET status=?, applied_at=? WHERE id=?",
            (status, datetime.now().isoformat(), job_id)
        )
    conn.commit()
    conn.close()


def get_pending_jobs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, title, company, location, url FROM jobs WHERE status='approved'"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4]} for r in rows]


def already_seen(job_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return row is not None


def reset_failed_jobs():
    """Reset all failed jobs back to approved so they get retried."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='approved' WHERE status='failed'")
    count = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return count


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text, reply_markup=None):
    from telegram_topics import TOPICS, GROUP_ID, TOKEN as TG_TOKEN
    payload = {
        "chat_id": GROUP_ID,
        "text": text,
        "parse_mode": "Markdown",
        "message_thread_id": TOPICS["jobs"],
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload)


def send_job_for_approval(job):
    markup = {
        "inline_keyboard": [[
            {"text": "✅ Apply", "callback_data": f"apply_{job['id']}"},
            {"text": "❌ Skip",  "callback_data": f"skip_{job['id']}"}
        ]]
    }
    text = (
        f"💼 *New Job Found*\n\n"
        f"*{job['title']}*\n"
        f"🏢 {job['company']}\n"
        f"📍 {job['location']}\n\n"
        f"[View Job]({job['url']})"
    )
    send_telegram(text, reply_markup=markup)


def handle_callback(update):
    callback = update.get("callback_query", {})
    data     = callback.get("data", "")
    msg_id   = callback.get("id")

    # Answer callback to remove loading state
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": msg_id})

    if data.startswith("apply_"):
        job_id = data[6:]
        update_job_status(job_id, "approved")
        send_telegram(f"✅ Marked for apply: `{job_id}`")

    elif data.startswith("skip_"):
        job_id = data[5:]
        update_job_status(job_id, "skipped")
        send_telegram(f"❌ Skipped: `{job_id}`")


# ── LinkedIn Playwright ───────────────────────────────────────────────────────

async def save_session(page):
    cookies = await page.context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies))


async def load_session(context):
    if SESSION_FILE.exists():
        data = json.loads(SESSION_FILE.read_text())
        cookies = data["cookies"] if isinstance(data, dict) and "cookies" in data else data
        # Fix domain: li_at must be on .linkedin.com not .www.linkedin.com
        for c in cookies:
            if c.get("domain", "").startswith(".www."):
                c["domain"] = c["domain"].replace(".www.", ".")
        await context.add_cookies(cookies)
        return True
    return False


async def login_linkedin_visible():
    """Open a visible browser, auto-fill credentials, and save session."""
    send_telegram("🔐 LinkedIn session expired — opening browser to re-login automatically...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Index 1 is the visible form (index 0 is a hidden duplicate)
            email_field = page.locator("input[type='email']").nth(1)
            pwd_field   = page.locator("input[type='password']").nth(1)
            await email_field.click(timeout=10000)
            await email_field.type(LINKEDIN_EMAIL, delay=50)
            await page.wait_for_timeout(500)

            await pwd_field.click(timeout=10000)
            await pwd_field.type(LINKEDIN_PASSWORD, delay=50)
            await page.wait_for_timeout(1000)

            # Click Sign in by text — button type changes after form fill
            signin_btn = page.get_by_role("button", name="Sign in").last
            await signin_btn.click(timeout=10000)
            await page.wait_for_timeout(3000)

            # Wait for feed — notify user if CAPTCHA appears
            try:
                await page.wait_for_url("**/feed/**", timeout=30000)
            except Exception:
                send_telegram("⚠️ LinkedIn login needs manual help — please complete CAPTCHA in the browser window that just opened.")
                await page.wait_for_url("**/feed/**", timeout=120000)

            await save_session(page)
            send_telegram("✅ LinkedIn re-logged in! Job search is ready.")
            print("✅ Session refreshed.")
        finally:
            await browser.close()


async def search_jobs(page, keyword):
    """Search Easy Apply jobs and return list of job cards."""
    url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={keyword.replace(' ', '%20')}"
        f"&location={LOCATION.replace(' ', '%20').replace(',', '%2C')}"
        f"&f_AL=true"
        f"&sortBy=DD"
    )
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Navigation error for '{keyword}': {e}")
        return []

    # If LinkedIn redirected us to login/authwall, session is expired
    if "login" in page.url or "authwall" in page.url or "checkpoint" in page.url:
        print(f"  Session expired during search (redirected to {page.url})")
        return []

    # Wait for job cards to render (up to 10s), then scroll to load more
    try:
        await page.wait_for_selector("a[href*='/jobs/view/']", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)

    # Guard against navigation that may have happened during the wait
    if "login" in page.url or "authwall" in page.url or "checkpoint" in page.url:
        print(f"  Redirected mid-search to {page.url}")
        return []

    try:
        await page.evaluate("window.scrollBy(0, 600)")
    except Exception as e:
        print(f"  Scroll failed (page navigated away): {e}")
        return []
    await page.wait_for_timeout(2000)

    jobs = []
    seen_ids = set()

    try:
        links = await page.query_selector_all("a[href*='/jobs/view/']")
    except Exception:
        return []

    for link in links[:20]:
        try:
            href  = await link.get_attribute("href") or ""
            title = (await link.inner_text()).strip()

            if not href or not title or len(title) < 3:
                continue

            # Extract numeric job ID from slug URL
            slug  = href.split("/jobs/view/")[1].split("?")[0].split("/")[0]
            # Last segment is the numeric ID: "dotnet-developer-at-tranzeal-4414123"
            parts  = slug.rsplit("-", 1)
            job_id = parts[-1] if parts[-1].isdigit() else slug

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Get company + location from parent li
            parent = await link.evaluate_handle("el => el.closest('li')")
            parent_el = parent.as_element() if parent else None

            company  = "Unknown Company"
            location = ""
            if parent_el:
                # Authenticated (logged-in) LinkedIn SPA selectors
                company_el = (
                    await parent_el.query_selector(".artdeco-entity-lockup__subtitle") or
                    await parent_el.query_selector("div[class*='subtitle']") or
                    await parent_el.query_selector(".job-card-container__primary-description") or
                    await parent_el.query_selector(".base-search-card__subtitle")
                )
                if company_el:
                    company = (await company_el.inner_text()).strip()

                location_el = (
                    await parent_el.query_selector(".job-card-container__metadata-wrapper") or
                    await parent_el.query_selector(".job-search-card__location") or
                    await parent_el.query_selector(".base-search-card__metadata")
                )
                if location_el:
                    location = (await location_el.inner_text()).strip().split("\n")[0]

            full_url = f"https://www.linkedin.com{href}" if href.startswith("/") else href
            # Normalise to www subdomain so session cookies always match
            full_url = full_url.replace("ie.linkedin.com", "www.linkedin.com")

            jobs.append({
                "id":       job_id,
                "title":    title,
                "company":  company,
                "location": location,
                "url":      full_url.split("?")[0],
            })

        except Exception:
            continue

    return jobs


async def dismiss_cookie_banner(page):
    """Dismiss LinkedIn's cookie consent banner if present."""
    try:
        # Try clicking the Accept button in the consent modal
        accepted = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            for (const btn of btns) {
                const label = (btn.getAttribute('aria-label') || btn.innerText || '').toLowerCase();
                if (label === 'accept' || label === 'accept cookies' || label === 'accept all') {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if accepted:
            await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _upload_resume_if_needed(page):
    """If the Easy Apply modal has a file-upload input, attach the PDF resume."""
    if not RESUME_PDF.exists():
        return
    try:
        file_inputs = await page.query_selector_all("input[type='file']")
        for fi in file_inputs:
            try:
                await fi.set_input_files(str(RESUME_PDF))
                await page.wait_for_timeout(800)
                print(f"  Uploaded resume: {RESUME_PDF.name}")
                return
            except Exception:
                continue
    except Exception:
        pass


async def apply_to_job(page, job):
    """Apply to a single Easy Apply job."""
    try:
        import random

        # Use LinkedIn's jobs search with currentJobId — loads the job in the
        job_id = job["id"]
        # Try search URL first, fall back to direct view URL
        urls_to_try = [
            f"https://www.linkedin.com/jobs/search/?currentJobId={job_id}",
            f"https://www.linkedin.com/jobs/view/{job_id}/",
        ]

        nav_ok = False
        for url_attempt, nav_url in enumerate(urls_to_try):
            for attempt in range(2):
                try:
                    await page.goto(nav_url, wait_until="domcontentloaded", timeout=30000)
                    nav_ok = True
                    break
                except Exception as nav_err:
                    wait = 10 + random.randint(5, 10)
                    print(f"  Nav error (url {url_attempt+1} attempt {attempt+1}): {nav_err} — waiting {wait}s...")
                    await page.wait_for_timeout(wait * 1000)
            if nav_ok:
                break

        if not nav_ok:
            print(f"  Nav failed for all URLs for {job['title']}")
            return False

        # Random human-like delay
        await page.wait_for_timeout(2000 + random.randint(500, 2000))

        # Dismiss cookie consent banner before looking for Easy Apply
        await dismiss_cookie_banner(page)
        await page.wait_for_timeout(500)

        # Find Easy Apply button via aria-label (works regardless of hashed CSS classes)
        apply_btn = (
            await page.query_selector("button[aria-label='Easy Apply to this job']") or
            await page.query_selector("button[aria-label*='Easy Apply']") or
            await page.query_selector("button.jobs-apply-button") or
            await page.query_selector("button[data-job-id]")
        )

        # Also try finding by button text
        if not apply_btn:
            apply_btn = await page.evaluate_handle("""() => {
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.innerText || '').trim();
                    if (t === 'Easy Apply' || t.startsWith('Easy Apply')) return btn;
                }
                return null;
            }""")
            try:
                if await apply_btn.evaluate("el => el === null"):
                    apply_btn = None
            except Exception:
                apply_btn = None

        if not apply_btn:
            # No Easy Apply — look for a plain "Apply" link/button that goes external
            ext_url = await page.evaluate("""() => {
                // Check buttons
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.innerText || btn.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (t === 'apply' || t === 'apply now' || t === 'apply on company website') {
                        btn.click();
                        return 'clicked';
                    }
                }
                // Check anchor tags
                for (const a of document.querySelectorAll('a')) {
                    const t = (a.innerText || a.getAttribute('aria-label') || '').trim().toLowerCase();
                    const href = a.href || '';
                    if ((t === 'apply' || t === 'apply now' || t === 'apply on company website')
                        && href && !href.includes('linkedin.com')) {
                        return href;
                    }
                }
                return null;
            }""")

            if ext_url == 'clicked':
                # Button clicked — wait for new tab or navigation
                await page.wait_for_timeout(3000)
                ext_url = page.url if 'linkedin.com' not in page.url else None

            if ext_url and 'linkedin.com' not in ext_url:
                print(f"  External apply link found: {ext_url[:80]}")
                try:
                    from external_apply import apply_external
                    return await apply_external(page, ext_url, job)
                except Exception as e:
                    print(f"  External apply error: {e}")
                    return False

            print(f"  No apply button found for {job['title']} — skipping")
            return False

        print(f"  Found Easy Apply button for {job['title']}, clicking...")
        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Redirected to external ATS — run the matching handler
        if 'linkedin.com' not in page.url:
            ext_url = page.url
            print(f"  Redirected to external site: {ext_url} — running external handler...")
            try:
                from external_apply import apply_external
                return await apply_external(page, ext_url, job)
            except Exception as e:
                print(f"  External apply error: {e}")
                return False

        # Upload PDF resume if the modal has a file input field
        await _upload_resume_if_needed(page)

        # Click through all Easy Apply steps using LinkedIn's pre-filled data
        review_count = 0
        for step in range(30):
            await dismiss_cookie_banner(page)
            await page.wait_for_timeout(1500)
            await _upload_resume_if_needed(page)

            # After hitting Review twice without Submit, scroll down and look harder for Submit
            if review_count >= 2:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(500)

            clicked = await page.evaluate("""() => {
                for (const btn of document.querySelectorAll('button')) {
                    const t = btn.innerText.trim();
                    const a = btn.getAttribute('aria-label') || '';
                    if (t === 'Submit application' || a.includes('Submit application')) {
                        btn.click(); return 'submit';
                    }
                }
                for (const btn of document.querySelectorAll('button')) {
                    const t = btn.innerText.trim();
                    const a = btn.getAttribute('aria-label') || '';
                    if (t === 'Review' || a.includes('Review your application')) {
                        btn.click(); return 'review';
                    }
                    if (t === 'Next' || a.includes('Continue to next step')) {
                        btn.click(); return 'next';
                    }
                    if (t === 'Done') {
                        btn.click(); return 'done';
                    }
                }
                return null;
            }""")

            print(f"  Step {step}: clicked={clicked}")
            if clicked == 'review':
                review_count += 1

            if clicked == 'submit':
                await page.wait_for_timeout(2000)
                print(f"  ✅ Applied to {job['title']} at {job['company']}")
                return True

            if clicked == 'done':
                print(f"  ✅ Applied to {job['title']} at {job['company']}")
                return True

            if clicked is None:
                all_btns = await page.evaluate("() => Array.from(document.querySelectorAll('button')).map(b => b.getAttribute('aria-label') || b.innerText.trim()).filter(t => t).slice(0,10)")
                print(f"  Step {step}: no nav button found — {all_btns}")
                break

        return False

    except Exception as e:
        print(f"  ❌ Error applying to {job['title']}: {e}")
        return False


async def find_and_connect_recruiter(page, job):
    """Search for recruiter/hiring manager at the company and send a connection request."""
    try:
        company_slug = job["company"].lower().replace(" ", "%20")
        search_url = (
            f"https://www.linkedin.com/search/results/people/?"
            f"keywords=recruiter+{company_slug}&origin=GLOBAL_SEARCH_HEADER"
        )
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find first person result with Connect button
        cards = await page.query_selector_all(".reusable-search__result-container")
        for card in cards[:5]:
            try:
                connect_btn = await card.query_selector("button[aria-label*='Connect']")
                name_el     = await card.query_selector(".entity-result__title-text")
                if not connect_btn or not name_el:
                    continue

                name = (await name_el.inner_text()).strip().split("\n")[0]
                await connect_btn.click()
                await page.wait_for_timeout(1500)

                # Add a note
                note_btn = await page.query_selector("button[aria-label='Add a note']")
                if note_btn:
                    await note_btn.click()
                    await page.wait_for_timeout(1000)
                    note_field = await page.query_selector("textarea#custom-message")
                    if note_field:
                        note_text = (
                            f"Hi {name.split()[0]}, I recently applied for the "
                            f"{job['title']} role at {job['company']}. "
                            f"I'm a DevOps/Cloud Engineer based in Dublin with hands-on experience in "
                            f"AWS, Docker, Kubernetes, CI/CD, and infrastructure automation. "
                            f"Would love to connect!"
                        )
                        await note_field.fill(note_text[:300])

                send_btn = await page.query_selector("button[aria-label='Send now']")
                if send_btn:
                    await send_btn.click()
                    await page.wait_for_timeout(1000)
                    return name

                # Close modal if send failed
                close = await page.query_selector("button[aria-label='Dismiss']")
                if close:
                    await close.click()

            except Exception:
                continue

        return None
    except Exception as e:
        print(f"  Recruiter search error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def find_jobs():
    """Find new Easy Apply jobs and send to Telegram for approval."""
    init_db()
    new_jobs = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--start-maximized"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        session_loaded = await load_session(context)
        if not session_loaded:
            await browser.close()
            await login_linkedin_visible()
            # Re-open headless browser with fresh session
            browser  = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
            context  = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            await load_session(context)
        else:
            await page.goto("https://www.linkedin.com/feed")
            await page.wait_for_timeout(2000)
            if "login" in page.url or "authwall" in page.url:
                print("Session expired, re-logging in...")
                await browser.close()
                await login_linkedin_visible()
                browser  = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
                context  = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = await context.new_page()
                await load_session(context)

        session_expired = False
        for keyword in JOB_KEYWORDS:
            print(f"Searching: {keyword}...")
            jobs = await search_jobs(page, keyword)

            # search_jobs returns [] on redirect or navigation error — check if session died
            if not jobs and any(s in page.url for s in ("login", "authwall", "checkpoint", "uas/")):
                print("Session expired mid-search — triggering re-login...")
                session_expired = True
                break

            for job in jobs:
                if not already_seen(job["id"]):
                    if is_fresher_role(job["title"]):
                        save_job(job)
                        # Auto-approve fresher/graduate roles — no manual tap needed
                        update_job_status(job["id"], "approved")
                        send_telegram(f"✅ *Auto-approved:* {job['title']} @ {job['company']}\n📍 {job['location']}")
                        new_jobs += 1
                    else:
                        save_job(job)
                        send_job_for_approval(job)
                        new_jobs += 1
                    await asyncio.sleep(1)

        await browser.close()

        if session_expired:
            await login_linkedin_visible()
            send_telegram("🔄 Session refreshed — please re-run /findjobs to continue the job search.")

    if new_jobs == 0:
        send_telegram("💼 *Job Search Complete*\nNo new Easy Apply jobs found matching your profile.")
    else:
        send_telegram(f"💼 Found *{new_jobs} new jobs*! Auto-applying to fresher/graduate roles now...\nSending /applyjobs automatically.")
        # Immediately apply to all auto-approved jobs
        await apply_approved()


async def apply_approved(from_find=False):
    """Apply to all Telegram-approved jobs."""
    init_db()
    approved = get_pending_jobs()

    if not approved:
        send_telegram("📋 No approved jobs to apply to yet. Use /findjobs first, then tap ✅ on jobs you want.")
        return

    send_telegram(f"🚀 Applying to *{len(approved)} approved jobs*...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--start-maximized",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        await load_session(context)

        # Try warming up the session with progressively simpler URLs
        session_ok = False
        for warmup_url, wu_wait in [
            ("https://www.linkedin.com/", "commit"),
            ("https://www.linkedin.com/jobs/", "commit"),
            ("https://www.linkedin.com/feed", "domcontentloaded"),
        ]:
            try:
                await page.goto(warmup_url, wait_until=wu_wait, timeout=30000)
                await page.wait_for_timeout(3000)
                if "login" not in page.url and "authwall" not in page.url and "checkpoint" not in page.url:
                    session_ok = True
                    print(f"Session warmed up via {warmup_url} → {page.url}")
                    break
            except Exception as e:
                print(f"Warmup nav error ({warmup_url}): {e}")

        if not session_ok:
            send_telegram("❌ LinkedIn session expired — please run `python fresh_login.py` then retry `/applyjobs`.")
            await browser.close()
            return

        # Allow LinkedIn's JS anti-bot checks to complete
        await page.wait_for_timeout(5000)

        applied = 0
        for job in approved:
            # 1. Tailor resume (reuse current page — no second browser opened)
            try:
                from resume_tailor import tailor_for_job
                tailored = await tailor_for_job(job, page=page)
                if tailored:
                    # Save to DB
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE jobs SET tailored_resume=? WHERE id=?", (tailored, job["id"]))
                    conn.commit()
                    conn.close()
                    send_telegram(
                        f"📄 *Tailored Resume for {job['title']} @ {job['company']}*\n\n"
                        f"```\n{tailored[:800]}...\n```\n_(full version saved)_"
                    )
            except Exception as e:
                print(f"  Resume tailor error: {e}")

            # 2. Apply
            try:
                success = await apply_to_job(page, job)
                status = "applied" if success else "failed"
            except Exception as e:
                print(f"  Apply error for {job['title']}: {e}")
                status = "failed"
                success = False
            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"✅ Applied: *{job['title']}* at {job['company']}")

                # 3. Recruiter outreach
                try:
                    recruiter = await find_and_connect_recruiter(page, job)
                    if recruiter:
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute(
                            "UPDATE jobs SET recruiter=? WHERE id=?",
                            (recruiter, job["id"])
                        )
                        conn.commit()
                        conn.close()
                        send_telegram(f"🤝 Connection request sent to recruiter at *{job['company']}*")
                except Exception as e:
                    print(f"  Recruiter outreach error: {e}")
            else:
                send_telegram(f"⚠️ Could not apply: *{job['title']}* at {job['company']}")

            await asyncio.sleep(random.randint(10, 20))

        await browser.close()

    send_telegram(f"🎉 Done! Applied to *{applied}/{len(approved)}* jobs.")


def poll_approvals():
    """Poll Telegram for ✅/❌ button taps."""
    offset = None
    print("Polling for approvals (30 seconds)...")
    end = time.time() + 30

    while time.time() < end:
        params = {"timeout": 5, "allowed_updates": ["callback_query"]}
        if offset:
            params["offset"] = offset
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=10)
        if resp.ok:
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                handle_callback(update)
        time.sleep(2)


async def auto_apply():
    """Find jobs and apply immediately — no Telegram approval step."""
    init_db()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        await load_session(context)
        await page.goto("https://www.linkedin.com/feed")
        await page.wait_for_timeout(2000)

        if "login" in page.url or "authwall" in page.url:
            print("Session expired, auto-relogging in...")
            await browser.close()
            await login_linkedin_visible()
            # Reopen headless browser with fresh session
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await load_session(context)
            await page.goto("https://www.linkedin.com/feed")
            await page.wait_for_timeout(2000)
            if "login" in page.url or "authwall" in page.url:
                send_telegram("LinkedIn re-login failed — please run `python3 linkedin_login_once.py` manually.")
                await browser.close()
                return

        # Phase 1: find all new jobs
        new_jobs = []
        for keyword in JOB_KEYWORDS:
            jobs = await search_jobs(page, keyword)
            for job in jobs:
                if not already_seen(job["id"]):
                    save_job(job)
                    update_job_status(job["id"], "approved")
                    new_jobs.append(job)
                    await asyncio.sleep(1)

        if not new_jobs:
            send_telegram("💼 *Auto Apply*\nNo new Easy Apply jobs found.")
            await browser.close()
            return

        send_telegram(f"💼 Found *{len(new_jobs)} new jobs* — applying now, no approval needed...")

        # Phase 2: apply immediately using LinkedIn's default resume
        applied = 0
        for job in new_jobs:
            try:
                success = await apply_to_job(page, job)
                status = "applied" if success else "failed"
            except Exception as e:
                print(f"  Apply error for {job['title']}: {e}")
                status = "failed"
                success = False
            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"✅ Applied: *{job['title']}* at {job['company']}")
                try:
                    recruiter = await find_and_connect_recruiter(page, job)
                    if recruiter:
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("UPDATE jobs SET recruiter=? WHERE id=?", (recruiter, job["id"]))
                        conn.commit()
                        conn.close()
                        send_telegram(f"🤝 Recruiter outreach sent at *{job['company']}*")
                except Exception as e:
                    print(f"  Recruiter error: {e}")
            else:
                send_telegram(f"⚠️ Could not apply: *{job['title']}* at {job['company']}")

            await asyncio.sleep(random.randint(10, 20))

        await browser.close()
    send_telegram(f"🎉 Done! *{applied}/{len(new_jobs)}* applications submitted.")


async def apply_saved_jobs():
    """Apply to all Easy Apply jobs in LinkedIn Saved Jobs."""
    init_db()
    send_telegram("🔖 Checking your LinkedIn Saved Jobs...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        await load_session(context)

        # Check session
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        if "login" in page.url or "authwall" in page.url:
            print("Session expired, re-logging in...")
            await browser.close()
            await login_linkedin_visible()
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
            context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            await load_session(context)

        # Navigate to Saved Jobs
        print("Loading saved jobs page...")
        await page.goto("https://www.linkedin.com/my-items/saved-jobs/", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        await dismiss_cookie_banner(page)
        await page.wait_for_timeout(500)

        # Scroll to load all saved jobs
        for _ in range(5):
            try:
                await page.evaluate("window.scrollBy(0, 800)")
            except Exception:
                break
            await page.wait_for_timeout(700)

        # Extract job cards
        saved_jobs = []
        cards = await page.query_selector_all("a[href*='/jobs/view/']")
        seen_ids = set()
        for card in cards:
            try:
                href = await card.get_attribute("href") or ""
                import re as _re
                m = _re.search(r"/jobs/view/(\d+)", href)
                if not m:
                    continue
                job_id = m.group(1)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                title = (await card.inner_text()).strip().split("\n")[0][:80]
                # Try to get company from sibling/parent
                company = ""
                try:
                    parent = await card.evaluate_handle("el => el.closest('li') || el.parentElement")
                    company_el = await parent.query_selector(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle")
                    if company_el:
                        company = (await company_el.inner_text()).strip()
                except Exception:
                    pass
                clean_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                saved_jobs.append({"id": job_id, "title": title, "company": company, "url": clean_url})
            except Exception:
                continue

        if not saved_jobs:
            send_telegram("🔖 No saved jobs found (or page didn't load correctly).")
            await browser.close()
            return

        send_telegram(f"🔖 Found *{len(saved_jobs)} saved jobs* — checking for Easy Apply...")
        print(f"Found {len(saved_jobs)} saved jobs")

        applied = 0
        external = []
        already_done = 0

        for job in saved_jobs:
            # Skip if already applied
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
            conn.close()
            if row and row[0] == "applied":
                already_done += 1
                continue

            # Save to DB if not there
            if not already_seen(job["id"]):
                save_job(job)
            update_job_status(job["id"], "approved")

            # Try Easy Apply
            try:
                success = await apply_to_job(page, job)
            except Exception as e:
                print(f"  Apply error: {e}")
                success = False

            if success:
                applied += 1
                update_job_status(job["id"], "applied")
                send_telegram(f"✅ Applied: *{job['title']}*" + (f" at {job['company']}" if job['company'] else ""))
                try:
                    recruiter = await find_and_connect_recruiter(page, job)
                    if recruiter:
                        send_telegram(f"🤝 Connection request sent to recruiter at *{job['company']}*")
                except Exception:
                    pass
            else:
                # Not Easy Apply — send link for manual application
                update_job_status(job["id"], "pending")
                external.append(job)

            await asyncio.sleep(3)

        await browser.close()

    # Send external jobs as clickable links for manual application
    if external:
        msg = f"📋 *{len(external)} saved job(s) need manual application* (no Easy Apply):\n\n"
        for j in external:
            label = j['title'] or 'Job'
            if j['company']:
                label += f" @ {j['company']}"
            msg += f"• [{label}]({j['url']})\n"
        send_telegram(msg)

    summary = f"🎉 Saved Jobs done!\n✅ Easy Applied: *{applied}*\n📋 Manual apply needed: *{len(external)}*"
    if already_done:
        summary += f"\n☑️ Already applied: *{already_done}*"
    send_telegram(summary)


async def do_login():
    """Open visible browser, auto-fill credentials and save session."""
    await login_linkedin_visible()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"

    if cmd == "find":
        asyncio.run(find_jobs())
    elif cmd == "apply":
        asyncio.run(apply_approved())
    elif cmd == "autoapply":
        asyncio.run(auto_apply())
    elif cmd == "savedjobs":
        asyncio.run(apply_saved_jobs())
    elif cmd == "poll":
        poll_approvals()
    elif cmd == "login":
        asyncio.run(do_login())
    elif cmd == "resetfailed":
        n = reset_failed_jobs()
        print(f"Reset {n} failed jobs to approved.")
    elif cmd == "retryall":
        n = reset_failed_jobs()
        print(f"Reset {n} failed jobs to approved — applying now...")
        asyncio.run(apply_approved())
