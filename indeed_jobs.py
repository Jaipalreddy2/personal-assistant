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

if sys.stdout is not None and hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None and hasattr(sys.stderr, "buffer") and getattr(sys.stderr, "encoding", "").lower() != "utf-8":
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

FRESHER_SEARCH_KEYWORDS = [
    "Junior DevOps Engineer",
    "Graduate DevOps Engineer",
    "Junior Cloud Engineer",
    "Graduate Software Engineer",
    "Junior Software Engineer",
    "Entry Level DevOps",
    "Junior Platform Engineer",
    "Associate DevOps Engineer",
    "Junior Python Developer",
    "Junior AWS Engineer",
    "Graduate Cloud Engineer",
    "Junior Site Reliability Engineer",
    "Entry Level Software Engineer",
    "Graduate IT Engineer",
]

INTERNSHIP_SEARCH_KEYWORDS = [
    "Software Engineer Intern",
    "DevOps Intern",
    "Cloud Engineer Intern",
    "IT Intern",
    "Python Developer Intern",
    "Data Engineer Intern",
    "Platform Engineer Intern",
    "AWS Intern",
    "Site Reliability Engineer Intern",
    "Software Intern",
    "Technology Intern",
    "Cloud Intern",
]

LAST_FIND_FILE = Path(__file__).parent / "last_indeed_find.txt"

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
        notes = "easy_apply" if job.get("easy_apply") else "external"
        conn.execute(
            "INSERT OR IGNORE INTO jobs (id, title, company, location, url, source, notes) VALUES (?,?,?,?,?,?,?)",
            (job["id"], job["title"], job["company"], job["location"], job["url"], job.get("source", "indeed"), notes),
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


def get_approved_indeed_jobs(since_dt=None):
    conn = sqlite3.connect(DB_PATH)
    if since_dt:
        rows = conn.execute(
            "SELECT id, title, company, location, url, notes FROM jobs WHERE status='approved' AND source='indeed' AND found_at >= ?",
            (since_dt,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, company, location, url, notes FROM jobs WHERE status='approved' AND source='indeed'"
        ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4], "notes": r[5] or ""} for r in rows]


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
    apply_tag = "⚡ Easy Apply" if job.get("easy_apply") else "🌐 External Apply"
    exp_emoji, exp_label = detect_experience_level(job["title"])
    text = (
        f"🔍 *Indeed Job* — {apply_tag}\n\n"
        f"*{job['title']}*\n"
        f"🏢 {job['company']}\n"
        f"📍 {job['location']}\n"
        f"📊 {exp_emoji} {exp_label}\n\n"
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


def detect_experience_level(title):
    """Detect experience level from job title. Returns (emoji, label) tuple."""
    t = title.lower()
    if any(w in t for w in ["intern", "internship", "placement", "work placement"]):
        return "🎓", "Internship"
    if any(w in t for w in ["junior", "jr.", "jr ", "graduate", "grad", "entry level",
                             "entry-level", "fresher", "trainee", "apprentice",
                             "associate", "early career", "new grad"]):
        return "🌱", "Fresher / Entry Level"
    if any(w in t for w in ["senior", "sr.", "sr ", "lead", "principal", "staff",
                             "manager", "director", "head of", "vp"]):
        return "⬆️", "Senior"
    return "💼", "Mid Level"


async def scrape_indeed_keyword(page, keyword, days=14, exp_level=None, job_type=None):
    """Scrape Indeed search results for one keyword. Returns list of job dicts."""
    p = {"q": keyword, "l": LOCATION, "sort": "date", "fromage": str(days)}
    if exp_level:
        p["explvl"] = exp_level   # e.g. ENTRY_LEVEL
    if job_type:
        p["jt"] = job_type        # e.g. internship
    url = f"https://ie.indeed.com/jobs?{urlencode(p)}"

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
        const jobLinks = document.querySelectorAll('a[data-jk]');
        for (const link of jobLinks) {
            try {
                const jk = link.getAttribute('data-jk');
                if (!jk) continue;

                const titleEl = link.querySelector('span[title]') || link.querySelector('span');
                const title = titleEl ? (titleEl.getAttribute('title') || titleEl.innerText || '').trim() : '';
                if (!title) continue;

                const li = link.closest('li');
                if (!li) continue;

                const compEl = li.querySelector('[data-testid="company-name"]');
                const company = compEl ? compEl.innerText.trim() : 'Unknown';

                const locEl = li.querySelector('[data-testid="text-location"]');
                const location = locEl ? locEl.innerText.trim() : 'Dublin, Ireland';

                // Detect "Easily apply" badge in card text
                const cardText = (li.innerText || '').toLowerCase();
                const easyApply = cardText.includes('easily apply');

                results.push({
                    id: 'indeed_' + jk,
                    title: title,
                    company: company,
                    location: location.split('\\n')[0].trim(),
                    url: 'https://ie.indeed.com/viewjob?jk=' + jk,
                    source: 'indeed',
                    easy_apply: easyApply,
                });
            } catch(e) {}
        }
        return results;
    }""")

    print(f"  Found {len(jobs)} cards for '{keyword}'")
    return jobs


async def find_jobs(keywords=None, exp_level=None, job_type=None, label="Jobs"):
    """Search keywords via Playwright, save new jobs, send to Telegram for approval."""
    init_db()
    from datetime import timedelta
    LAST_FIND_FILE.write_text((datetime.utcnow() - timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S'))
    if keywords is None:
        keywords = JOB_KEYWORDS
    all_new = []
    seen_this_run = set()

    async with async_playwright() as p:
        context = await get_indeed_context(p, headless=True)
        page = await context.new_page()

        for kw in keywords:
            print(f"Searching Indeed: {kw}")
            jobs = await scrape_indeed_keyword(page, kw, exp_level=exp_level, job_type=job_type)
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
        send_telegram(f"🔍 *Indeed {label}*: No new jobs found this time.")
        return

    # Mark all found jobs as approved and show summary
    for job in all_new:
        update_job_status(job["id"], "approved")

    lines = [f"🔍 *Indeed {label}*: Found *{len(all_new)} new jobs*\n"]
    for job in all_new:
        exp_emoji, exp_label = detect_experience_level(job["title"])
        apply_tag = "⚡" if job.get("easy_apply") else "🌐"
        lines.append(f"• *{job['title']}* @ {job['company']}\n  {apply_tag} {exp_emoji} {exp_label}")
    send_telegram("\n".join(lines))


async def find_fresher_jobs():
    """Find entry-level / fresher jobs on Indeed only."""
    await find_jobs(
        keywords=FRESHER_SEARCH_KEYWORDS,
        exp_level="ENTRY_LEVEL",
        label="Fresher / Entry Level Jobs"
    )


async def find_internship_jobs():
    """Find internship jobs on Indeed only."""
    await find_jobs(
        keywords=INTERNSHIP_SEARCH_KEYWORDS,
        job_type="internship",
        label="Internship Jobs"
    )

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
    """Navigate to job page and apply.

    "Apply with Indeed" jobs: fills Indeed SmartApply form (requires login).
    "Apply on company site" jobs: sends direct apply link to Telegram.
    Returns (success, reason) tuple.
    """
    try:
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000 + random.randint(500, 1500))

        # Detect which button is present
        btn_type = await page.evaluate("""() => {
            if (document.querySelector('button[aria-label="Apply with Indeed"]'))
                return 'indeed';
            for (const btn of document.querySelectorAll('button')) {
                const t = (btn.innerText || btn.textContent || '').toLowerCase();
                if (t.includes('company site') || t.includes('company website'))
                    return 'external';
            }
            return 'unknown';
        }""")

        # ── External apply: send link to Telegram ─────────────────────────
        if btn_type != 'indeed':
            applystart = f"https://ie.indeed.com/applystart?jk={job['id'].replace('indeed_', '')}&from=vj"
            send_telegram(
                f"🌐 *{job['title']}* at {job['company']}\n"
                f"[Apply on company site]({applystart})"
            )
            return True, ""

        # ── Apply with Indeed → SmartApply form ───────────────────────────
        apply_btn = await page.query_selector('button[aria-label="Apply with Indeed"]')
        if not apply_btn:
            send_telegram(f"⚠️ Button missing for *{job['title']}* — [apply manually]({job['url']})")
            return False, "Apply with Indeed button not found on page"

        await apply_btn.scroll_into_view_if_needed()
        await apply_btn.click()
        await page.wait_for_timeout(3000)

        # If not logged in, will land on auth page
        if "secure.indeed.com/auth" in page.url or "accounts.indeed.com" in page.url:
            send_telegram(
                f"🔐 Indeed login needed — run /ind\\_login first, then retry /ind\\_apply\n"
                f"Or [apply manually]({job['url']})"
            )
            return False, "Not logged in to Indeed — run /ind_login"

        # SmartApply form is at smartapply.indeed.com
        # Wait for the form to load
        try:
            await page.wait_for_url("*smartapply.indeed.com*", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        # Upload resume
        await _upload_resume(page)

        # Fill common form fields across SmartApply pages
        async def fill_fields():
            try:
                for sel in ["input[name='name']", "input[autocomplete='name']", "input[placeholder*='name' i]"]:
                    el = await page.query_selector(sel)
                    if el and not await el.input_value():
                        await el.fill("Jaipal Kasi Reddy")
                        break
            except Exception:
                pass
            try:
                for sel in ["input[type='tel']", "input[name*='phone']", "input[placeholder*='phone' i]"]:
                    el = await page.query_selector(sel)
                    if el and not await el.input_value():
                        await el.fill(PHONE_NUMBER)
                        break
            except Exception:
                pass
            try:
                for sel in ["input[type='email']", "input[name*='email']"]:
                    el = await page.query_selector(sel)
                    if el and not await el.input_value():
                        await el.fill(INDEED_EMAIL)
                        break
            except Exception:
                pass
            # Fill required text inputs with sensible defaults
            try:
                await page.evaluate("""() => {
                    for (const inp of document.querySelectorAll('input[required], textarea[required]')) {
                        if (inp.value) continue;
                        const lbl = (inp.getAttribute('aria-label') || inp.placeholder || '').toLowerCase();
                        if (lbl.includes('year') || lbl.includes('experience')) inp.value = '1';
                        else if (lbl.includes('city') || lbl.includes('location')) inp.value = 'Dublin';
                        else if (lbl.includes('salary')) inp.value = '40000';
                    }
                    for (const sel of document.querySelectorAll('select[required]')) {
                        if (!sel.value && sel.options.length > 1) sel.selectedIndex = 1;
                    }
                }""")
            except Exception:
                pass

        await fill_fields()

        # Step through multi-page SmartApply form (up to 10 steps)
        for step in range(10):
            await page.wait_for_timeout(1500)
            await fill_fields()

            # Success
            if ("confirmation" in page.url or "thankyou" in page.url.lower()
                    or "applied" in page.url.lower()):
                return True, ""
            success_el = await page.query_selector(
                "[class*='confirmation'], [class*='success'], h1[class*='thank'], "
                "h2[class*='applied'], [data-testid*='confirmation']"
            )
            if success_el:
                return True, ""

            # Submit button
            submit_btn = None
            for sel in ["button[type='submit']", "button[data-testid*='submit']"]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        t = (await el.inner_text()).strip().lower()
                        if "submit" in t or "send" in t:
                            submit_btn = el
                            break
                except Exception:
                    continue
            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(3000)
                return True, ""

            # Continue / Next
            next_btn = await page.evaluate_handle("""() => {
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.innerText || '').trim().toLowerCase();
                    if (['continue', 'next', 'next step', 'save and continue'].includes(t)) return btn;
                }
                return null;
            }""")
            try:
                if not await next_btn.evaluate("el => el === null"):
                    await next_btn.click()
                    continue
            except Exception:
                pass
            break

        return False, "SmartApply form did not reach confirmation after all steps"

    except Exception as e:
        print(f"  Indeed apply error for {job['title']}: {e}")
        return False, str(e)


async def apply_approved():
    """Apply to Indeed jobs approved from the most recent /findindeed session."""
    init_db()
    since_dt = None
    if LAST_FIND_FILE.exists():
        try:
            since_dt = LAST_FIND_FILE.read_text().strip()
        except Exception:
            pass
    approved = get_approved_indeed_jobs(since_dt=since_dt)
    if not approved:
        send_telegram("📋 No new approved Indeed jobs. Run /findindeed first, then approve jobs.")
        return

    async with async_playwright() as p:
        context, page = await ensure_indeed_session(p, send_telegram)
        if context is None:
            return

        send_telegram(f"✅ Indeed active — applying to *{len(approved)} jobs* now...")

        applied = 0
        for job in approved:
            is_easy = job.get("notes", "") == "easy_apply"
            try:
                success, reason = await apply_to_indeed_job(page, job)
                status  = "applied" if success else "failed"
            except Exception as e:
                reason  = str(e)
                status  = "failed"
                success = False

            update_job_status(job["id"], status)

            if success:
                applied += 1
                if is_easy:
                    send_telegram(f"✅ Applied (Indeed Easy Apply): *{job['title']}* at {job['company']}")
                # External jobs — link already sent inside apply_to_indeed_job
            else:
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

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


def approve_all_pending():
    """Bulk-approve all pending Indeed jobs — no Telegram tap needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='approved' WHERE source='indeed' AND status='pending'")
    count = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return count


async def auto_apply_indeed():
    """Find Indeed jobs and apply immediately — no approval step."""
    init_db()

    # Phase 1: scrape all keywords
    all_new = []
    seen_this_run = set()

    async with async_playwright() as p:
        context = await get_indeed_context(p, headless=True)
        page = await context.new_page()

        for kw in JOB_KEYWORDS:
            print(f"Searching: {kw}")
            jobs = await scrape_indeed_keyword(page, kw)
            for job in jobs:
                if job["id"] in seen_this_run or already_seen(job["id"]):
                    continue
                if not _is_relevant(job["title"]):
                    continue
                seen_this_run.add(job["id"])
                notes = "easy_apply" if job.get("easy_apply") else "external"
                job["notes"] = notes
                save_job(job)
                update_job_status(job["id"], "approved")
                all_new.append(job)
            await asyncio.sleep(random.randint(2, 4))

        await context.close()

    if not all_new:
        send_telegram("🔍 *Indeed Auto Apply*: No new jobs found.")
        return

    send_telegram(f"💼 Found *{len(all_new)} new Indeed jobs* — applying now, no approval needed...")

    # Phase 2: apply
    async with async_playwright() as p:
        context, page = await ensure_indeed_session(p, send_telegram)
        if context is None:
            return

        applied = 0
        for job in all_new:
            try:
                success, reason = await apply_to_indeed_job(page, job)
                status = "applied" if success else "failed"
            except Exception as e:
                reason = str(e)
                status = "failed"
                success = False

            update_job_status(job["id"], status)
            if success and job.get("notes") == "easy_apply":
                applied += 1
                send_telegram(f"✅ Applied: *{job['title']}* at {job['company']}")
            elif not success:
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

            await asyncio.sleep(random.randint(8, 15))

        await context.close()

    send_telegram(f"🎉 Done! *{applied}/{len(all_new)}* Indeed applications submitted.")


async def apply_indeed_saved():
    """Apply to jobs saved/bookmarked on Indeed."""
    init_db()
    send_telegram("🔖 Checking your Indeed Saved Jobs...")

    async with async_playwright() as p:
        context, page = await ensure_indeed_session(p, send_telegram)
        if context is None:
            return

        try:
            await page.goto("https://ie.indeed.com/profile/savedJobs", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            saved = await page.evaluate("""() => {
                const results = [];
                for (const a of document.querySelectorAll('a[data-jk], a[href*="viewjob"]')) {
                    const jk = a.getAttribute('data-jk') || (a.href.split('jk=')[1] || '').split('&')[0];
                    if (!jk) continue;
                    const titleEl = a.querySelector('span[title], span') || a;
                    const title = (titleEl.getAttribute('title') || titleEl.innerText || '').trim();
                    if (!title || title.length < 3) continue;
                    const li = a.closest('li, article, div[class*="job"]');
                    const compEl = li ? li.querySelector('[data-testid="company-name"], [class*="company"]') : null;
                    results.push({
                        id: 'indeed_' + jk,
                        title: title,
                        company: compEl ? compEl.innerText.trim() : 'Unknown',
                        location: 'Dublin, Ireland',
                        url: 'https://ie.indeed.com/viewjob?jk=' + jk,
                    });
                }
                return results;
            }""")

            if not saved:
                send_telegram("🔖 No saved jobs found on Indeed. Save jobs on ie.indeed.com first.")
                await context.close()
                return

            send_telegram(f"🔖 Found *{len(saved)} saved Indeed jobs* — applying now...")

            applied = 0
            for job in saved:
                job["source"] = "indeed"
                job["notes"] = "external"  # will be re-detected in apply_to_indeed_job
                if not already_seen(job["id"]):
                    save_job(job)
                    update_job_status(job["id"], "approved")

                try:
                    success, reason = await apply_to_indeed_job(page, job)
                    status = "applied" if success else "failed"
                except Exception as e:
                    reason = str(e)
                    status = "failed"
                    success = False

                update_job_status(job["id"], status)
                if success:
                    applied += 1
                elif reason:
                    msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}\n  Reason: {reason}"
                    send_telegram(msg)
                await asyncio.sleep(random.randint(8, 15))

            await context.close()
            send_telegram(f"🎉 Done! Processed *{applied}/{len(saved)}* Indeed saved jobs.")

        except Exception as e:
            await context.close()
            send_telegram(f"⚠️ Error reading saved jobs: {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    if cmd == "find":
        asyncio.run(find_jobs())
    elif cmd == "findfresher":
        asyncio.run(find_fresher_jobs())
    elif cmd == "findinternship":
        asyncio.run(find_internship_jobs())
    elif cmd == "apply":
        asyncio.run(apply_approved())
    elif cmd == "login":
        asyncio.run(login_indeed_visible())
    elif cmd == "autoapply":
        asyncio.run(auto_apply_indeed())
    elif cmd == "savedjobs":
        asyncio.run(apply_indeed_saved())
    elif cmd == "approveall":
        n = approve_all_pending()
        send_telegram(f"✅ Approved *{n} Indeed jobs*. Run /applyindeed to apply.")
