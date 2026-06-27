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
from linkedin_browser import get_context, is_logged_in, ensure_active_session

# Force UTF-8 output on Windows to support emoji in print statements
if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr is not None and hasattr(sys.stderr, 'buffer') and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
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

# Role must contain at least one of these to be considered relevant tech role
TECH_KEYWORDS = [
    "engineer", "developer", "devops", "cloud", "platform", "software",
    "infrastructure", "sre", "reliability", "python", "aws", "kubernetes",
    "docker", "backend", "fullstack", "full stack", "full-stack",
    "it ", "data", "systems", "network", "security", "support",
    "technical", "computing", "automation",
]


def is_fresher_role(title):
    """Return True if the job title is a relevant tech role for a fresher/graduate."""
    title_lower = title.lower()
    if any(kw in title_lower for kw in SENIOR_KEYWORDS):
        return False
    if not any(kw in title_lower for kw in TECH_KEYWORDS):
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

LINKEDIN_EMAIL    = config.get("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = config.get("LINKEDIN_PASSWORD")
PHONE_NUMBER      = config.get("PHONE", "+353870042809")

LOCATION        = "Dublin, Ireland"
DB_PATH         = Path(__file__).parent / "applied_jobs.db"
SESSION_FILE    = Path(__file__).parent / "linkedin_session.json"
RESUME_PDF      = Path(__file__).parent / "Jaipal_Kasi_Reddy_Resume.pdf"
LAST_FIND_FILE  = Path(__file__).parent / "last_linkedin_find.txt"


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


def get_pending_jobs(since_dt=None):
    conn = sqlite3.connect(DB_PATH)
    if since_dt:
        rows = conn.execute(
            "SELECT id, title, company, location, url FROM jobs WHERE status='approved' AND found_at >= ?",
            (since_dt,)
        ).fetchall()
    else:
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
        for c in cookies:
            if c.get("domain", "").startswith(".www."):
                c["domain"] = c["domain"].replace(".www.", ".")
        await context.add_cookies(cookies)
        return True
    return False


async def ensure_session(p):
    """Return (context, page) — auto-opens visible browser if session expired."""
    return await ensure_active_session(p, send_telegram)


async def login_linkedin_visible():
    """Open the persistent Chrome profile visibly for re-login."""
    send_telegram("🔐 Opening browser for LinkedIn login — sign in and the window will close automatically.")
    async with async_playwright() as p:
        context = await get_context(p, headless=False)
        page = await context.new_page()
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            if "feed" in page.url:
                send_telegram("✅ Already logged in!")
                return

            try:
                await page.wait_for_selector("#username, input[name='session_key']", timeout=15000)
                email_sel = "#username" if await page.query_selector("#username") else "input[name='session_key']"
                pwd_sel   = "#password" if await page.query_selector("#password") else "input[name='session_password']"
                await page.fill(email_sel, LINKEDIN_EMAIL)
                await page.wait_for_timeout(600)
                await page.fill(pwd_sel, LINKEDIN_PASSWORD)
                await page.wait_for_timeout(600)
                await page.click("button[type='submit']")
            except Exception:
                send_telegram("⚠️ Auto-fill failed — please log in manually in the browser window.")

            try:
                await page.wait_for_url("**/feed**", timeout=180000)
            except Exception:
                pass

            if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
                send_telegram("✅ LinkedIn logged in! Session saved. Future operations run headlessly.")
                print("Session saved to persistent profile.")
            else:
                send_telegram(f"❌ Login may not have completed (URL: {page.url}). Try again.")
        finally:
            await context.close()


async def search_jobs(page, keyword, date_filter=None, exp_filter=None, job_type_filter=None):
    """Search Easy Apply jobs and return list of job cards."""
    url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={keyword.replace(' ', '%20')}"
        f"&location={LOCATION.replace(' ', '%20').replace(',', '%2C')}"
        f"&f_AL=true"
        f"&sortBy=DD"
    )
    if date_filter:
        url += f"&f_TPR={date_filter}"
    if exp_filter:
        url += f"&f_E={exp_filter}"
    if job_type_filter:
        url += f"&f_JT={job_type_filter}"
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

            exp_emoji, exp_label = detect_experience_level(title)
            jobs.append({
                "id":               job_id,
                "title":            title,
                "company":          company,
                "location":         location,
                "url":              full_url.split("?")[0],
                "exp_emoji":        exp_emoji,
                "exp_label":        exp_label,
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


async def _fill_required_fields(page):
    """Auto-fill any required fields in the Easy Apply modal that are empty."""
    try:
        await page.evaluate(f"""async () => {{
            const phone = "{PHONE_NUMBER}";
            // Fill empty phone inputs
            for (const inp of document.querySelectorAll('input[type="tel"], input[id*="phone"], input[name*="phone"]')) {{
                if (!inp.value) inp.value = phone;
            }}
            // Answer "Yes" to work authorisation / sponsorship radio groups
            for (const radio of document.querySelectorAll('input[type="radio"]')) {{
                const lbl = (radio.getAttribute('aria-label') || '').toLowerCase();
                const parentText = (radio.closest('fieldset')?.innerText || '').toLowerCase();
                if ((lbl.includes('yes') || lbl.includes('authorized') || lbl.includes('eligible'))
                    && !radio.checked) {{
                    radio.click();
                }}
                // Select "No" for sponsorship needed
                if ((parentText.includes('sponsor') && (lbl.includes('no') || lbl === 'no'))
                    && !radio.checked) {{
                    radio.click();
                }}
            }}
            // Fill required empty text inputs with sensible defaults
            for (const inp of document.querySelectorAll('input[required], input[aria-required="true"]')) {{
                if (!inp.value && inp.type === 'text') {{
                    const lbl = (inp.getAttribute('aria-label') || inp.getAttribute('placeholder') || '').toLowerCase();
                    if (lbl.includes('year') || lbl.includes('experience')) inp.value = '1';
                    else if (lbl.includes('salary') || lbl.includes('rate')) inp.value = '40000';
                    else if (lbl.includes('city') || lbl.includes('location')) inp.value = 'Dublin';
                    else if (lbl.includes('linkedin') || lbl.includes('profile')) inp.value = 'https://www.linkedin.com/in/jaipal-kasi-reddy';
                    else if (lbl.includes('github') || lbl.includes('portfolio') || lbl.includes('website')) inp.value = 'https://github.com/Jaipalreddy2';
                }}
            }}
            // Select first option in empty required dropdowns
            for (const sel of document.querySelectorAll('select[required], select[aria-required="true"]')) {{
                if (!sel.value && sel.options.length > 1) sel.selectedIndex = 1;
            }}
        }};""")
    except Exception as e:
        print(f"  Field fill error: {e}")


async def apply_to_job(page, job):
    """Apply to a single Easy Apply job. Returns (success, reason) tuple."""
    try:
        job_id = job["id"]
        urls_to_try = [
            f"https://www.linkedin.com/jobs/search/?currentJobId={job_id}",
            f"https://www.linkedin.com/jobs/view/{job_id}/",
        ]

        nav_ok = False
        for nav_url in urls_to_try:
            for attempt in range(2):
                try:
                    await page.goto(nav_url, wait_until="domcontentloaded", timeout=30000)
                    nav_ok = True
                    break
                except Exception as nav_err:
                    print(f"  Nav error: {nav_err}")
                    await page.wait_for_timeout(8000)
            if nav_ok:
                break

        if not nav_ok:
            print(f"  Nav failed: {job['title']}")
            return False, "Could not load job page (navigation timeout)"

        await page.wait_for_timeout(2000 + random.randint(500, 1500))
        await dismiss_cookie_banner(page)
        await page.wait_for_timeout(500)

        # Dismiss any "unfinished application" dialog first
        try:
            discard = await page.query_selector("button[aria-label='Discard'], button[data-control-name='discard_application']")
            if discard:
                await discard.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # ── Find Easy Apply element (button or <a> tag) ─────────────────────
        # LinkedIn renders Easy Apply as <a> or <button> depending on layout.
        # Wait up to 8s for it to appear (LinkedIn lazy-loads the apply button).
        apply_el = None
        apply_href = None

        # Strategy 1: wait_for_selector across both a and button variants
        for sel in [
            "a[aria-label='Easy Apply to this job']",
            "a[aria-label*='Easy Apply']",
            "button[aria-label='Easy Apply to this job']",
            "button[aria-label*='Easy Apply']",
            "button.jobs-apply-button",
        ]:
            try:
                apply_el = await page.wait_for_selector(sel, timeout=3000)
                if apply_el:
                    tag = await apply_el.evaluate("el => el.tagName")
                    if tag == "A":
                        apply_href = await apply_el.get_attribute("href")
                    break
            except Exception:
                continue

        # Strategy 2: Playwright text locator across all clickable elements
        if not apply_el:
            try:
                loc = page.locator("a, button, [role='button']").filter(has_text="Easy Apply")
                if await loc.count() > 0:
                    apply_el = loc.first
                    tag = await apply_el.evaluate("el => el.tagName")
                    if tag == "A":
                        apply_href = await apply_el.get_attribute("href")
            except Exception:
                pass

        # Strategy 3: JS search across all elements including aria-label
        if not apply_el and not apply_href:
            result = await page.evaluate("""() => {
                const els = [...document.querySelectorAll('button, a, [role="button"]')];
                for (const el of els) {
                    const t = (el.innerText || el.textContent || '').trim();
                    const a = el.getAttribute('aria-label') || '';
                    if (t === 'Easy Apply' || a.toLowerCase().includes('easy apply'))
                        return { tag: el.tagName, href: el.getAttribute('href') || '' };
                }
                return null;
            }""")
            if result:
                apply_href = result.get("href") or None

        if not apply_el and not apply_href:
            # No Easy Apply — try external apply link
            ext_url = await page.evaluate("""() => {
                for (const a of document.querySelectorAll('a[href]')) {
                    const t = (a.innerText || a.getAttribute('aria-label') || '').trim().toLowerCase();
                    const href = a.href || '';
                    if ((t.includes('apply') || t === 'apply now') && !href.includes('linkedin.com'))
                        return href;
                }
                return null;
            }""")
            if ext_url:
                print(f"  External link: {ext_url[:80]}")
                try:
                    from external_apply import apply_external
                    result = await apply_external(page, ext_url, job)
                    return result, ("" if result else "External site apply failed")
                except Exception as e:
                    print(f"  External apply error: {e}")
                    return False, f"External site error: {e}"
            print(f"  No apply button found for {job['title']}")
            return False, "No Easy Apply button — job requires applying on company site"

        print(f"  Easy Apply found: {job['title']} @ {job['company']}")

        # Navigate directly via href if available (more reliable than clicking)
        if apply_href and "linkedin.com" in apply_href:
            await page.goto(apply_href, wait_until="domcontentloaded", timeout=30000)
        elif apply_el:
            await apply_el.scroll_into_view_if_needed()
            await apply_el.click()
        await page.wait_for_timeout(2000)

        # Redirected to external ATS
        if 'linkedin.com' not in page.url:
            try:
                from external_apply import apply_external
                result = await apply_external(page, page.url, job)
                return result, ("" if result else "External ATS apply failed")
            except Exception as e:
                print(f"  External apply error: {e}")
                return False, f"External ATS error: {e}"

        # ── Walk through Easy Apply steps ──────────────────────────────────
        await _upload_resume_if_needed(page)

        review_count = 0
        stuck_count  = 0
        for step in range(35):
            await dismiss_cookie_banner(page)
            await page.wait_for_timeout(1200)
            await _upload_resume_if_needed(page)
            await _fill_required_fields(page)

            if review_count >= 2:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(400)

            clicked = await page.evaluate("""() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const find = (...labels) => buttons.find(b => {
                    const t = (b.innerText || '').trim();
                    const a = b.getAttribute('aria-label') || '';
                    return labels.some(l => t === l || a.includes(l));
                });
                const submit = find('Submit application', 'Submit Application');
                if (submit) { submit.click(); return 'submit'; }
                const done = find('Done');
                if (done) { done.click(); return 'done'; }
                const review = find('Review', 'Review your application');
                if (review) { review.click(); return 'review'; }
                const next = find('Next', 'Continue to next step', 'Continue');
                if (next) { next.click(); return 'next'; }
                // Dismiss "Follow company" or success modals
                const dismiss = find('Dismiss', 'Not now', 'Skip');
                if (dismiss) { dismiss.click(); return 'dismiss'; }
                return null;
            }""")

            print(f"  Step {step}: {clicked}")

            if clicked == 'review':
                review_count += 1
            elif clicked == 'submit':
                await page.wait_for_timeout(2000)
                print(f"  ✅ Applied: {job['title']} @ {job['company']}")
                return True, ""
            elif clicked == 'done':
                print(f"  ✅ Applied: {job['title']} @ {job['company']}")
                return True, ""
            elif clicked is None:
                stuck_count += 1
                if stuck_count >= 2:
                    btns = await page.evaluate("() => Array.from(document.querySelectorAll('button')).map(b => (b.innerText||b.getAttribute('aria-label')||'').trim()).filter(t=>t).slice(0,8)")
                    print(f"  Stuck at step {step}. Buttons: {btns}")
                    return False, f"Form stuck — buttons visible: {', '.join(btns) if btns else 'none'}"
                await page.wait_for_timeout(2000)

        return False, "Form did not reach submit after all steps"

    except Exception as e:
        print(f"  ❌ Error applying to {job['title']}: {e}")
        return False, str(e)


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

async def find_jobs(keywords=None, exp_filter=None, job_type_filter=None, label="Jobs"):
    """Find new relevant Easy Apply jobs and list them in Telegram. Does NOT apply."""
    init_db()
    from datetime import timedelta
    LAST_FIND_FILE.write_text((datetime.utcnow() - timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S'))
    if keywords is None:
        keywords = JOB_KEYWORDS
    new_jobs = 0
    found_jobs = []

    async with async_playwright() as p:
        context, page = await ensure_session(p)
        if context is None:
            return

        session_expired = False
        for keyword in keywords:
            print(f"Searching: {keyword}...")
            jobs = await search_jobs(page, keyword, exp_filter=exp_filter, job_type_filter=job_type_filter)

            if not jobs and any(s in page.url for s in ("login", "authwall", "checkpoint", "uas/")):
                print("Session expired mid-search — triggering re-login...")
                session_expired = True
                break

            for job in jobs:
                if not already_seen(job["id"]) and is_fresher_role(job["title"]):
                    save_job(job)
                    update_job_status(job["id"], "approved")
                    found_jobs.append(job)
                    new_jobs += 1
                    await asyncio.sleep(0.5)

        await context.close()

        if session_expired:
            send_telegram("❌ LinkedIn session expired mid-search — please run /login, then retry.")

    if new_jobs == 0:
        send_telegram(f"💼 *{label} Search Complete*\nNo new jobs found. Try again later.")
        return

    lines = [f"💼 *Found {new_jobs} new {label}*\n"]
    for j in found_jobs:
        loc = f" · {j['location']}" if j.get('location') else ""
        exp = f"{j.get('exp_emoji','💼')} {j.get('exp_label','')}"
        lines.append(f"• *{j['title']}* @ {j['company']}{loc}\n  {exp}")
    send_telegram("\n".join(lines))


async def find_fresher_jobs():
    """Find entry-level and fresher jobs only (LinkedIn f_E=2 filter)."""
    await find_jobs(
        keywords=FRESHER_SEARCH_KEYWORDS,
        exp_filter="2",  # Entry level
        label="Fresher / Entry Level Jobs"
    )


async def find_internship_jobs():
    """Find internship jobs only (LinkedIn f_JT=I filter)."""
    await find_jobs(
        keywords=INTERNSHIP_SEARCH_KEYWORDS,
        job_type_filter="I",  # Internship job type
        label="Internship Jobs"
    )


async def apply_approved(from_find=False):
    """Apply to all Telegram-approved jobs."""
    init_db()
    approved = get_pending_jobs()

    if not approved:
        send_telegram("📋 No approved jobs to apply to yet. Use /findjobs first, then tap ✅ on jobs you want.")
        return

    send_telegram(f"🚀 Applying to *{len(approved)} approved jobs*...")

    async with async_playwright() as p:
        context, page = await ensure_session(p)
        if context is None:
            return

        await page.wait_for_timeout(3000)

        applied = 0
        for job in approved:
            # 1. Tailor resume silently — save to DB, no Telegram spam
            try:
                from resume_tailor import tailor_for_job
                tailored = await tailor_for_job(job, page=page)
                if tailored:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE jobs SET tailored_resume=? WHERE id=?", (tailored, job["id"]))
                    conn.commit()
                    conn.close()
                    print(f"  Resume tailored for {job['title']}")
            except Exception as e:
                print(f"  Resume tailor error: {e}")

            # 2. Apply
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
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

            await asyncio.sleep(random.randint(10, 20))

        await context.close()

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
        context, page = await ensure_session(p)
        if context is None:
            return

        # Phase 1: find new jobs posted in last 4 weeks
        FOUR_WEEKS = "r2419200"
        new_jobs = []
        for keyword in JOB_KEYWORDS:
            jobs = await search_jobs(page, keyword, date_filter=FOUR_WEEKS)
            for job in jobs:
                if not already_seen(job["id"]):
                    save_job(job)
                    update_job_status(job["id"], "approved")
                    new_jobs.append(job)
                    await asyncio.sleep(1)

        if not new_jobs:
            send_telegram("💼 *Auto Apply*\nNo new Easy Apply jobs found.")
            await context.close()
            return

        send_telegram(f"💼 Found *{len(new_jobs)} new jobs* — applying now, no approval needed...")

        # Phase 2: apply immediately using LinkedIn's default resume
        applied = 0
        for job in new_jobs:
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
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

            await asyncio.sleep(random.randint(10, 20))

        await context.close()
    send_telegram(f"🎉 Done! *{applied}/{len(new_jobs)}* applications submitted.")


async def apply_saved_jobs():
    """Apply to all Easy Apply jobs in LinkedIn Saved Jobs."""
    init_db()
    send_telegram("🔖 Checking your LinkedIn Saved Jobs...")

    async with async_playwright() as p:
        context, page = await ensure_session(p)
        if context is None:
            return

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
            await context.close()
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
                success, reason = await apply_to_job(page, job)
            except Exception as e:
                reason = str(e)
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
                if reason and "No Easy Apply" not in reason:
                    msg = f"⚠️ Could not apply: *{job['title']}*" + (f" at {job['company']}" if job['company'] else "")
                    msg += f"\n  Reason: {reason}"
                    send_telegram(msg)
                # Not Easy Apply — send link for manual application
                update_job_status(job["id"], "pending")
                external.append(job)

            await asyncio.sleep(3)

        await context.close()

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


async def login_then_apply():
    """Apply to jobs found in the most recent /findjobs session only."""
    init_db()
    since_dt = None
    if LAST_FIND_FILE.exists():
        try:
            since_dt = LAST_FIND_FILE.read_text().strip()
        except Exception:
            pass
    approved = get_pending_jobs(since_dt=since_dt)
    if not approved:
        send_telegram("📋 No new approved jobs to apply to. Run /findjobs first.")
        return

    async with async_playwright() as p:
        context, page = await ensure_session(p)
        if context is None:
            return

        send_telegram(f"✅ LinkedIn active — applying to *{len(approved)} jobs* now...")

        # Apply without closing the browser
        applied = 0
        for job in approved:
            try:
                from resume_tailor import tailor_for_job
                tailored = await tailor_for_job(job, page=page)
                if tailored:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE jobs SET tailored_resume=? WHERE id=?", (tailored, job["id"]))
                    conn.commit()
                    conn.close()
            except Exception as e:
                print(f"  Resume tailor error: {e}")

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
                try:
                    recruiter = await find_and_connect_recruiter(page, job)
                    if recruiter:
                        send_telegram(f"🤝 Connection request sent to recruiter at *{job['company']}*")
                except Exception:
                    pass
            else:
                msg = f"⚠️ Could not apply: *{job['title']}* at {job['company']}"
                if reason:
                    msg += f"\n  Reason: {reason}"
                send_telegram(msg)

            await asyncio.sleep(random.randint(8, 15))

        await context.close()
    send_telegram(f"🎉 Done! Applied to *{applied}/{len(approved)}* jobs.")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"

    if cmd == "find":
        asyncio.run(find_jobs())
    elif cmd == "findfresher":
        asyncio.run(find_fresher_jobs())
    elif cmd == "findinternship":
        asyncio.run(find_internship_jobs())
    elif cmd == "apply":
        asyncio.run(apply_approved())
    elif cmd == "loginapply":
        asyncio.run(login_then_apply())
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
        asyncio.run(login_then_apply())
