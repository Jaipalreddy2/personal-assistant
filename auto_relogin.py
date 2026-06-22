#!/usr/bin/env python3
"""
Auto-refresh LinkedIn session using a visible browser.
Called automatically when session expires — no user input needed unless
LinkedIn shows a verification challenge.
"""
import sys, io, asyncio, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path

config   = dotenv_values(Path.home() / ".env")
EMAIL    = config.get("LINKEDIN_EMAIL")
PASSWORD = config.get("LINKEDIN_PASSWORD")
SESSION  = Path(__file__).parent / "linkedin_session.json"


def notify_telegram(msg):
    try:
        import requests
        from dotenv import dotenv_values
        from pathlib import Path
        cfg = dotenv_values(Path.home() / ".env")
        token    = cfg.get("TELEGRAM_BOT_TOKEN")
        group_id = cfg.get("TELEGRAM_GROUP_ID")
        topic    = int(cfg.get("TELEGRAM_TOPIC_CHAT", 2))
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": group_id, "text": msg, "message_thread_id": topic},
            timeout=10
        )
    except Exception:
        pass


async def relogin():
    print("Auto-relogin: launching visible browser...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )

        # Load saved cookies first
        if SESSION.exists():
            try:
                data = json.loads(SESSION.read_text())
                cookies = data.get("cookies", data) if isinstance(data, dict) else data
                # Fix domain: li_at must be on .linkedin.com not .www.linkedin.com
                for c in cookies:
                    if c.get("domain", "").startswith(".www."):
                        c["domain"] = c["domain"].replace(".www.", ".")
                if cookies:
                    await context.add_cookies(cookies)
            except Exception:
                pass

        page = await context.new_page()

        # Navigate directly to /feed — if cookies are valid LinkedIn serves it.
        # Avoid /login as it can create redirect loops with valid cookies loaded.
        print("Checking session by navigating to /feed...")
        notify_telegram("Checking LinkedIn session...")
        try:
            await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"Feed nav error: {e}")
        await page.wait_for_timeout(4000)
        print(f"After /feed nav, URL: {page.url}")

        if page.url.startswith("https://www.linkedin.com/feed") or \
           page.url.startswith("https://www.linkedin.com/mynetwork"):
            print("Remember-me cookies valid — session refreshed.")
            new_cookies = await context.cookies()
            SESSION.write_text(json.dumps({"cookies": new_cookies}))
            notify_telegram("LinkedIn session is active.")
            await browser.close()
            return True

        # Not on feed — need to log in
        print("Session expired. Navigating to /login to fill credentials...")
        notify_telegram("Refreshing LinkedIn session — logging in now...")

        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Login page nav error: {e}")

        try:
            await page.wait_for_selector("#username, input[name='session_key']", timeout=15000)
            email_sel = "#username" if await page.query_selector("#username") else "input[name='session_key']"
            pwd_sel   = "#password" if await page.query_selector("#password") else "input[name='session_password']"
            await page.fill(email_sel, EMAIL)
            await page.wait_for_timeout(400)
            await page.fill(pwd_sel, PASSWORD)
            await page.wait_for_timeout(400)
            await page.click("button[type=submit]")
            await page.wait_for_timeout(4000)
            print(f"After submit, URL: {page.url}")
        except Exception as e:
            if page.url.startswith("https://www.linkedin.com/feed"):
                print("Already on feed after navigation.")
            else:
                print(f"Could not fill login form: {e}")
                await browser.close()
                notify_telegram(
                    "LinkedIn auto-login failed — could not fill form.\n"
                    "Please run: `python3 linkedin_login_once.py`"
                )
                return False

        # Wait up to 60 seconds for feed (covers verification if needed)
        try:
            await page.wait_for_url("**/feed/**", timeout=30000)
        except Exception:
            if "checkpoint" in page.url or "challenge" in page.url:
                notify_telegram(
                    "LinkedIn login needs verification.\n"
                    "Complete it in the browser window that just opened on your PC (within 60 seconds)."
                )
                print("Waiting for user to complete verification...")
                try:
                    await page.wait_for_url("**/feed/**", timeout=60000)
                except Exception:
                    print(f"Login timed out. URL: {page.url}")
                    await browser.close()
                    notify_telegram("LinkedIn login timed out. Run `python3 linkedin_login_once.py` manually.")
                    return False
            elif not page.url.startswith("https://www.linkedin.com/feed"):
                print(f"Login failed. URL: {page.url}")
                await browser.close()
                notify_telegram("LinkedIn login failed. Please run `python3 linkedin_login_once.py`")
                return False

        # Save fresh session
        cookies = await context.cookies()
        SESSION.write_text(json.dumps({"cookies": cookies}))
        print("LinkedIn session refreshed successfully.")
        notify_telegram("LinkedIn session refreshed — job search ready.")
        await browser.close()
        return True


def run():
    return asyncio.run(relogin())


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
