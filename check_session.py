import json, time
from pathlib import Path
from playwright.async_api import async_playwright
import asyncio

data = json.loads(Path("linkedin_session.json").read_text())
cookies = data.get("cookies", data) if isinstance(data, dict) else data

for c in cookies:
    if c["name"] in ("li_at", "li_rm", "JSESSIONID"):
        print(f"{c['name']}: domain={c.get('domain')} expires={c.get('expires')}")

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        for c in cookies:
            if c.get("domain", "").startswith(".www."):
                c["domain"] = c["domain"].replace(".www.", ".")
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        print(f"URL after goto /feed: {page.url}")
        print(f"Session valid: {'feed' in page.url}")
        await browser.close()

asyncio.run(test())
