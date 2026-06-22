"""
Shared LinkedIn browser utilities — persistent Chrome profile.

Uses launch_persistent_context so LinkedIn always sees the same browser identity.
Session cookies survive reboots. No cookie injection = no fingerprint detection.
"""
from pathlib import Path
from dotenv import dotenv_values

_config = dotenv_values(Path.home() / ".env")
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


async def get_context(playwright, headless: bool = True):
    """Launch (or resume) the persistent LinkedIn Chrome profile."""
    return await playwright.chromium.launch_persistent_context(
        PROFILE_DIR,
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


async def ensure_active_session(playwright, send_telegram_fn):
    """Return (context, page) — auto-opens visible browser if session expired.

    Handles re-login transparently so callers never need to show an error.
    send_telegram_fn is called to notify the user (pass send_telegram from the caller).
    """
    context = await get_context(playwright, headless=True)
    page = await context.new_page()
    if await is_logged_in(page):
        return context, page

    # Session expired — switch to visible browser for re-login
    await page.close()
    await context.close()
    send_telegram_fn("🔐 LinkedIn session expired — opening browser on your PC. Sign in and the bot will continue automatically.")

    context = await get_context(playwright, headless=False)
    page = await context.new_page()
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)

    # Try auto-fill credentials
    try:
        await page.wait_for_selector("#username, input[name='session_key']", timeout=15000)
        email_sel = "#username" if await page.query_selector("#username") else "input[name='session_key']"
        pwd_sel   = "#password" if await page.query_selector("#password") else "input[name='session_password']"
        await page.fill(email_sel, _EMAIL)
        await page.wait_for_timeout(600)
        await page.fill(pwd_sel, _PASSWORD)
        await page.wait_for_timeout(600)
        await page.click("button[type='submit']")
    except Exception:
        send_telegram_fn("⚠️ Auto-fill failed — please log in manually in the browser window.")

    try:
        await page.wait_for_url("**/feed**", timeout=180000)
    except Exception:
        pass

    if "feed" in page.url or page.url.startswith("https://www.linkedin.com/in/"):
        send_telegram_fn("✅ Logged in! Continuing...")
        return context, page

    await context.close()
    send_telegram_fn("❌ Login timed out. Please try the command again.")
    return None, None
