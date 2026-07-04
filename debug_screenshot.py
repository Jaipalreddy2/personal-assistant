"""Find the Easy Apply element — check buttons, a tags, role=button elements."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    from linkedin_browser import get_context, is_logged_in

    async with async_playwright() as p:
        context = await get_context(p, headless=False)
        page = await context.new_page()

        await is_logged_in(page)

        job_id = "4425285572"
        await page.goto(f"https://www.linkedin.com/jobs/view/{job_id}/", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # Check ALL clickable elements (buttons + a + role=button) for Easy Apply text
        results = await page.evaluate("""() => {
            const all = [
                ...document.querySelectorAll('button'),
                ...document.querySelectorAll('a'),
                ...document.querySelectorAll('[role="button"]'),
            ];
            return all.map(el => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '').trim().substring(0, 80),
                aria: el.getAttribute('aria-label') || '',
                href: el.getAttribute('href') || '',
                classes: el.className.substring(0, 60),
                visible: el.offsetParent !== null,
            })).filter(el =>
                el.text.toLowerCase().includes('apply') ||
                el.aria.toLowerCase().includes('apply') ||
                el.href.toLowerCase().includes('apply')
            );
        }""")

        print(f"Elements containing 'apply' ({len(results)} found):")
        for r in results:
            print(f"  <{r['tag']}> text='{r['text']}' | aria='{r['aria']}' | visible={r['visible']}")
            print(f"    href='{r['href'][:80]}' | classes='{r['classes']}'")

        # Also try Playwright's built-in locator
        try:
            btn = page.get_by_role("button", name="Easy Apply")
            count = await btn.count()
            print(f"\nPlaywright get_by_role('button', name='Easy Apply'): {count} found")
        except Exception as e:
            print(f"\nPlaywright locator error: {e}")

        # Try any element with Easy Apply text
        try:
            loc = page.locator("text=Easy Apply")
            count = await loc.count()
            print(f"Playwright locator('text=Easy Apply'): {count} found")
            for i in range(count):
                el = loc.nth(i)
                tag = await el.evaluate("el => el.tagName")
                print(f"  [{i}] <{tag}>")
        except Exception as e:
            print(f"Playwright text locator error: {e}")

        input("\nPress Enter to close...")
        await context.close()


asyncio.run(main())
