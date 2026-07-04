#!/usr/bin/env python3
"""Debug: why does Easy Apply not open a modal for NoFrixion?"""
import asyncio, sys, io, sqlite3
from pathlib import Path

if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from playwright.async_api import async_playwright
from linkedin_browser import ensure_active_session, is_logged_in
from linkedin_apply import DB_PATH, send_telegram

async def main():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id FROM jobs WHERE title LIKE '%Full Stack%' AND company='NoFrixion' LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        print("Job not found"); return
    job_id = row[0]

    async with async_playwright() as p:
        context, page = await ensure_active_session(p, send_telegram)
        await page.wait_for_timeout(10000)

        url = f"https://www.linkedin.com/jobs/search/?currentJobId={job_id}"
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"Current URL: {page.url}")

        # Find all apply-related buttons/links
        buttons = await page.evaluate("""() => {
            const results = [];
            for (const el of document.querySelectorAll('button, a[href]')) {
                const t = (el.innerText || el.textContent || '').trim().slice(0, 60);
                const a = el.getAttribute('aria-label') || '';
                const href = el.getAttribute('href') || '';
                if (t.toLowerCase().includes('apply') || a.toLowerCase().includes('apply')) {
                    results.push({
                        tag: el.tagName,
                        text: t,
                        ariaLabel: a,
                        href: href.slice(0, 100),
                        disabled: el.disabled || false,
                        classes: el.className.slice(0, 60)
                    });
                }
            }
            return results;
        }""")
        print(f"\nApply buttons found: {len(buttons)}")
        for b in buttons:
            print(f"  {b['tag']} text={b['text']!r} aria={b['ariaLabel']!r} href={b['href']!r} disabled={b['disabled']}")

        # Try clicking the Easy Apply button
        apply_el = None
        for sel in ["a[aria-label*='Easy Apply']","button[aria-label*='Easy Apply']","button.jobs-apply-button"]:
            apply_el = await page.query_selector(sel)
            if apply_el:
                print(f"\nFound apply element with selector: {sel}")
                tag = await apply_el.evaluate("el => el.tagName")
                href = await apply_el.get_attribute("href") or ""
                print(f"  Tag: {tag}, href: {href}")
                break

        if apply_el:
            print("\nClicking Easy Apply...")
            await apply_el.click()
            await page.wait_for_timeout(3000)
            print(f"URL after click: {page.url}")

            modal = await page.query_selector(".jobs-easy-apply-modal, [data-test-modal], .artdeco-modal")
            print(f"Modal found: {modal is not None}")

            if not modal:
                print("Page content after click (first 500 chars):")
                content = await page.evaluate("() => document.body.innerText.slice(0, 500)")
                print(content)

        await context.close()

asyncio.run(main())
