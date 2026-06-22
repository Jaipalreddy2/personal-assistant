import sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import linkedin_apply as la
from playwright.async_api import async_playwright

async def test():
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        print("Loading saved session...")
        await la.load_session(context)
        print("Navigating to LinkedIn feed...")
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"Feed URL: {page.url}")

        if "login" in page.url or "authwall" in page.url:
            print("SESSION EXPIRED — need re-login with linkedin_login_once.py")
            await browser.close()
            return

        print("Session valid!")
        kw = la.JOB_KEYWORDS[0]
        print(f"Searching keyword: {kw}")
        jobs = await la.search_jobs(page, kw)
        print(f"Found {len(jobs)} jobs")
        new = [j for j in jobs if not la.already_seen(j["id"])]
        print(f"New (not in DB): {len(new)}")
        for j in new[:5]:
            print(f"  {j['title']} @ {j['company']}")
        await browser.close()

asyncio.run(test())
