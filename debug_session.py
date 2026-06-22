#!/usr/bin/env python3
"""Debug exactly where LinkedIn redirects us."""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from playwright.async_api import async_playwright

SESSION = Path(__file__).parent / "linkedin_session.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

async def test():
    data = json.loads(SESSION.read_text())
    cookies = data.get("cookies", data)
    for c in cookies:
        if c.get("domain","").startswith(".www."):
            c["domain"] = c["domain"].replace(".www.", ".")
    print("Cookies:")
    for c in cookies:
        print(f"  {c['name']}: domain={c['domain']} len={len(str(c['value']))}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,   # visible
            args=["--no-sandbox","--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width":1280,"height":800})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        redirects = []
        page.on("response", lambda r: redirects.append(f"  {r.status} {r.url[:80]}") if r.status in (301,302,307,308) else None)

        print("\nNavigating to linkedin.com homepage...")
        try:
            await page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=20000)
            print(f"Landed: {page.url}")
        except Exception as e:
            print(f"Error on homepage: {e}")

        print(f"\nRedirects so far:\n" + ("\n".join(redirects[-20:]) if redirects else "  none"))
        redirects.clear()

        print("\nWaiting 3s then navigating to /feed...")
        await page.wait_for_timeout(3000)
        try:
            await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=20000)
            print(f"Landed: {page.url}")
        except Exception as e:
            print(f"Error on /feed: {e}")

        print(f"\nRedirects:\n" + ("\n".join(redirects[-20:]) if redirects else "  none"))

        print("\nBrowser staying open for 10s so you can see what's showing...")
        await page.wait_for_timeout(10000)
        await browser.close()

asyncio.run(test())
