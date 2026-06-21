"""Debug: show what's on each saved job page."""
import sys, io, asyncio, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
import linkedin_apply as la

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        await la.load_session(context)

        # Load saved jobs page
        await page.goto("https://www.linkedin.com/my-items/saved-jobs/", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        print("Saved jobs URL after load:", page.url)
        try:
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 600)")
                await page.wait_for_timeout(700)
        except Exception as e:
            print(f"Scroll error (navigation?): {e}")

        print("=== SAVED JOBS PAGE ===")
        print("URL:", page.url)

        # Get all job links
        links = await page.query_selector_all("a[href*='/jobs/view/']")
        print(f"Job links found: {len(links)}")
        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()[:80]
            print(f"  LINK: {href[:60]} | TEXT: {text[:50]}")

        # Get all buttons on saved jobs page
        btns = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('button'))
            .map(b => (b.getAttribute('aria-label') || b.innerText || '').trim())
            .filter(t => t && t.length < 80)
        """)
        print(f"\nButtons on saved jobs page: {btns[:20]}")

        # Navigate to first job if found
        if links:
            href = await links[0].get_attribute("href")
            import re
            m = re.search(r"/jobs/view/(\d+)", href)
            if m:
                job_url = f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
                print(f"\n=== JOB PAGE: {job_url} ===")
                await page.goto(job_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await la.dismiss_cookie_banner(page)
                await page.wait_for_timeout(500)

                print("URL:", page.url)
                title_el = await page.query_selector("h1")
                title = (await title_el.inner_text()).strip() if title_el else "?"
                print("Title:", title)

                btns2 = await page.evaluate("""() =>
                    Array.from(document.querySelectorAll('button'))
                    .map(b => (b.getAttribute('aria-label') || b.innerText || '').trim())
                    .filter(t => t && t.length < 100)
                """)
                print(f"Buttons: {btns2[:20]}")

                easy_apply = await page.query_selector("button[aria-label*='Easy Apply']")
                print(f"Easy Apply selector found: {easy_apply is not None}")

        await browser.close()

asyncio.run(main())
