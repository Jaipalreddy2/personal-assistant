"""
Shared LinkedIn browser utilities — persistent Chrome profile.

Uses launch_persistent_context so LinkedIn always sees the same browser identity.
Session cookies survive reboots. No cookie injection = no fingerprint detection.
"""
from pathlib import Path

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
