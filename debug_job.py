#!/usr/bin/env python3
"""Debug a specific job application with visible browser."""
import sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
import linkedin_apply as la

# Test a specific job
TEST_URL = "https://www.linkedin.com/jobs/view/cloud-engineer-at-berkley-group-4425649229"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        await la.load_session(context)

        print("Navigating to job page...")
        try:
            await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Nav error: {e}")
            await page.wait_for_timeout(5000)

        print(f"URL: {page.url}")
        await page.wait_for_timeout(3000)
        await la.dismiss_cookie_banner(page)

        # Check all buttons
        btns = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('button, a'))
            .map(b => ({
                tag: b.tagName,
                text: (b.innerText || '').trim().substring(0, 50),
                aria: b.getAttribute('aria-label') || '',
                href: b.href || '',
                class: b.className.substring(0, 40)
            }))
            .filter(b => b.text && b.text.length > 1)
            .slice(0, 30)
        """)
        print("\n=== All buttons/links on page ===")
        for b in btns:
            print(f"  [{b['tag']}] text='{b['text']}' aria='{b['aria']}' href='{b['href'][:60]}'")

        # Specifically check for Easy Apply
        easy = await page.query_selector("button[aria-label*='Easy Apply']")
        apply_generic = await page.query_selector("button[aria-label*='Apply']")
        print(f"\nEasy Apply button: {easy is not None}")
        print(f"Any Apply button: {apply_generic is not None}")

        # Wait to observe
        print("\nPausing 10s so you can see the page...")
        await page.wait_for_timeout(10000)
        await browser.close()

asyncio.run(main())
