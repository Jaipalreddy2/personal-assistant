"""
Shared LinkedIn browser utilities — persistent Chrome profile.

Uses launch_persistent_context so LinkedIn always sees the same browser identity.
Session cookies survive reboots. No cookie injection = no fingerprint detection.
"""
import sys, io
from pathlib import Path
from dotenv import dotenv_values

# Ensure stdout can handle emoji on Windows (cp1252 can't).
# Only re-wrap if not already UTF-8 — double-wrapping closes the underlying buffer.
if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr is not None and hasattr(sys.stderr, 'buffer') and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_config   = dotenv_values(Path.home() / ".env")
_EMAIL    = _config.get("LINKEDIN_EMAIL", "")
_PASSWORD = _config.get("LINKEDIN_PASSWORD", "")

PROFILE_DIR = str(Path(__file__).parent / "linkedin_chrome_profile")

_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-infobars",
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Ordered from most reliable to least — tries each until one works
_EMAIL_SELECTORS = [
    "input[autocomplete='username']",
    "#username",
    "input[name='session_key']",
    "input[type='email']",
]
_PWD_SELECTORS = [
    "input[autocomplete='current-password']",
    "#password",
    "input[name='session_password']",
    "input[type='password']",
]


async def get_context(playwright, headless: bool = True):
    """Launch (or resume) the persistent LinkedIn Chrome profile.
    Uses real installed Google Chrome (channel='chrome') so LinkedIn
    doesn't fingerprint-block Playwright's bundled Chromium.
    """
    return await playwright.chromium.launch_persistent_context(
        PROFILE_DIR,
        channel="chrome",
        headless=headless,
        args=_ARGS,
        viewport={"width": 1366, "height": 768},
        user_agent=_UA,
        locale="en-IE",
    )


async def is_logged_in(page) -> bool:
    """Navigate to /feed and return True if session is active."""
    try:
        await page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
            timeout=25000,
        )
        await page.wait_for_timeout(2000)
        url = page.url
        return (
            "feed" in url
            and "login" not in url
            and "authwall" not in url
            and "checkpoint" not in url
        )
    except Exception:
        return False


async def _find_and_fill(page, selectors, value):
    """Try each selector until one is visible and fillable. Returns True on success."""
    # Give LinkedIn up to 30s to render the form
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=30000)
            el = page.locator(sel).first
            await el.scroll_into_view_if_needed()
            await el.click()
            await page.wait_for_timeout(300)
            await el.clear()
            await el.type(value, delay=60)  # human-like keystroke delay
            return True
        except Exception:
            continue
    return False


async def _autofill_login(page, send_telegram_fn):
    """Attempt to fill and submit the LinkedIn login form. Returns True if submitted."""
    # Wait for the page to fully settle before looking for inputs
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    if "feed" in page.url:
        return True  # already logged in

    filled_email = await _find_and_fill(page, _EMAIL_SELECTORS, _EMAIL)
    if not filled_email:
        send_telegram_fn("⚠️ Could not find email field — please log in manually in the browser window.")
        return False

    await page.wait_for_timeout(500)

    filled_pwd = await _find_and_fill(page, _PWD_SELECTORS, _PASSWORD)
    if not filled_pwd:
        send_telegram_fn("⚠️ Could not find password field — please log in manually.")
        return False

    await page.wait_for_timeout(500)

    # Submit — try button click first, fall back to Enter key
    try:
        btn = page.locator("button[type='submit'], button[data-litms-control-urn*='sign-in']").first
        await btn.click(timeout=5000)
    except Exception:
        try:
            await page.keyboard.press("Enter")
        except Exception:
            pass

    return True


async def ensure_active_session(playwright, send_telegram_fn):
    """Return (context, page) using persistent profile.

    If session is expired, opens a visible browser, auto-fills credentials,
    and waits for login before returning. Caller never sees an error message.
    """
    context = await get_context(playwright, headless=True)
    page = await context.new_page()
    if await is_logged_in(page):
        return context, page

    # Session expired — reopen visibly for re-login
    await page.close()
    await context.close()
    send_telegram_fn("🔐 LinkedIn session expired — opening browser and signing in automatically...")

    context = await get_context(playwright, headless=False)
    page = await context.new_page()

    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass

    submitted = await _autofill_login(page, send_telegram_fn)
    if submitted:
        send_telegram_fn("⏳ Credentials submitted — waiting for LinkedIn to load...")

    # Wait up to 3 min for feed (covers 2FA / CAPTCHA cases)
    try:
        await page.wait_for_url("**/feed**", timeout=180000)
    except Exception:
        pass

    if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
        send_telegram_fn("✅ Logged in! Continuing...")
        return context, page

    # Still not logged in — maybe 2FA or CAPTCHA
    send_telegram_fn("⚠️ Waiting for you to complete login (2FA/CAPTCHA?) — up to 3 more minutes...")
    try:
        await page.wait_for_url("**/feed**", timeout=180000)
    except Exception:
        pass

    if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
        send_telegram_fn("✅ Logged in! Continuing...")
        return context, page

    await context.close()
    send_telegram_fn("❌ Login timed out. Please run /login and sign in manually, then retry.")
    return None, None
