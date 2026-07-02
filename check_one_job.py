import asyncio, sys, io, sqlite3
from pathlib import Path

if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from playwright.async_api import async_playwright
from linkedin_browser import get_context
from linkedin_apply import DB_PATH

async def main():
    # Check Realtime Recruitment job
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id, url FROM jobs WHERE company='Realtime Recruitment' AND title='DevOps Engineer'").fetchone()
    conn.close()
    if not row: print("Not found"); return
    job_id, url = row
    print(f"Job ID: {job_id}, URL: {url}")

    async with async_playwright() as p:
        ctx = await get_context(p, headless=False)
        page = await ctx.new_page()
        await page.goto(f"https://www.linkedin.com/jobs/search/?currentJobId={job_id}", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        print(f"Page URL: {page.url}")

        # Check what's on the page
        info = await page.evaluate("""() => {
            const h1 = document.querySelector('h1')?.innerText || '';
            const applyBtns = [...document.querySelectorAll('button,a')].filter(e =>
                (e.innerText||e.getAttribute('aria-label')||'').toLowerCase().includes('apply')
            ).map(e => ({text: (e.innerText||'').trim().slice(0,40), label: e.getAttribute('aria-label')||'', tag: e.tagName}));
            const noLonger = document.body?.innerText?.includes('No longer accepting') || false;
            const jobTitle = document.querySelector('.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title')?.innerText || '';
            return { h1, applyBtns: applyBtns.slice(0,5), noLonger, jobTitle };
        }""")
        print(f"Job title on page: {info['jobTitle']}")
        print(f"No longer accepting: {info['noLonger']}")
        print(f"Apply buttons: {info['applyBtns']}")
        await asyncio.sleep(5)
        await ctx.close()

asyncio.run(main())
