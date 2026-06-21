#!/usr/bin/env python3
"""One-shot: re-login to LinkedIn + scrape profile to extract resume data."""
import asyncio, json, sys, io
from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

config = dotenv_values(Path.home() / '.env')
EMAIL    = config.get('LINKEDIN_EMAIL')
PASSWORD = config.get('LINKEDIN_PASSWORD')
SESSION_FILE = Path(__file__).parent / 'linkedin_session.json'


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        # ── Load saved session if it exists ───────────────────────────────
        if SESSION_FILE.exists():
            saved = json.loads(SESSION_FILE.read_text())
            cookie_list = saved.get('cookies', saved) if isinstance(saved, dict) else saved
            await context.add_cookies(cookie_list)
            print("Loaded saved session cookies.")

        # ── Navigate to login and let LinkedIn decide ──────────────────────
        # If "remember me" cookies are valid, LinkedIn auto-redirects to /feed/
        print("Navigating to LinkedIn login...")
        await page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded')
        await page.wait_for_timeout(4000)
        print("After login nav, URL:", page.url)

        on_feed = page.url.startswith('https://www.linkedin.com/feed') or \
                  page.url.startswith('https://www.linkedin.com/mynetwork')

        if on_feed:
            print("Auto-logged in via saved cookies!")
        elif 'login' in page.url or 'authwall' in page.url:
            # Need fresh login — fill credentials
            print("Filling login credentials...")
            try:
                await page.wait_for_selector('#username', timeout=10000)
                await page.fill('#username', EMAIL)
                await page.fill('#password', PASSWORD)
                await page.click('button[type=submit]')
                await page.wait_for_timeout(6000)
                print("After submit, URL:", page.url)
            except Exception as e:
                print("Could not fill login form:", e)

            if 'checkpoint' in page.url or 'challenge' in page.url:
                print("LinkedIn requires verification. Complete it in the browser window.")
                print("Press Enter here when done...")
                input()
        else:
            print("Unexpected URL after login, continuing:", page.url)

        # Save fresh session cookies
        cookies = await context.cookies()
        SESSION_FILE.write_text(json.dumps({'cookies': cookies}))
        print("Session saved.")

        # ── Navigate to own profile ────────────────────────────────────────
        await page.goto('https://www.linkedin.com/in/me/', wait_until='domcontentloaded')
        await page.wait_for_timeout(5000)
        print("Profile URL:", page.url)

        # ── Scroll aggressively to trigger lazy-load ───────────────────────
        print("Scrolling to load all sections...")
        prev_height = 0
        for attempt in range(15):
            await page.evaluate("window.scrollBy(0, 1200)")
            await page.wait_for_timeout(800)
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break  # no more content loading
            prev_height = curr_height
        # scroll back to top so profile header is visible for selectors
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)

        # ── Save HTML AFTER scrolling ──────────────────────────────────────
        html = await page.content()
        Path(__file__).parent.joinpath('profile_debug.html').write_text(html, encoding='utf-8')

        # ── Extract via JavaScript innerText on component sections ─────────
        def clean(text):
            import re
            return re.sub(r'\s+', ' ', text or '').strip()

        # Use page.evaluate to get text from sections by component key suffix
        async def get_section_text(key_contains):
            return await page.evaluate(f"""
                (() => {{
                    const el = document.querySelector('[componentkey*="{key_contains}"]');
                    return el ? el.innerText : '';
                }})()
            """)

        # Basics from h2 (LinkedIn renders name as h2 on profile)
        name = clean(await page.evaluate("""
            (() => {
                const els = document.querySelectorAll('h1, h2');
                for (const el of els) {
                    const t = el.innerText.trim();
                    if (t && t.length > 3 && t.length < 60 && !t.includes('notification')) return t;
                }
                return document.title.split('|')[0].trim();
            })()
        """))

        headline = clean(await page.evaluate("""
            (() => {
                // headline is usually the first div after the name h2 with medium text
                const name_el = document.querySelector('h2');
                if (name_el) {
                    let sib = name_el.nextElementSibling;
                    while (sib) {
                        const t = sib.innerText.trim();
                        if (t && t.length > 5 && t.length < 200) return t;
                        sib = sib.nextElementSibling;
                    }
                }
                return '';
            })()
        """))

        location = clean(await get_section_text('Topcard'))
        # location is inside topcard section, extract the location line
        for line in location.split('\n'):
            line = line.strip()
            if 'Ireland' in line or 'Dublin' in line or 'London' in line:
                location = line
                break

        print(f"Name:     {name}")
        print(f"Headline: {headline}")
        print(f"Location: {location}")

        # ── About ──────────────────────────────────────────────────────────
        about_raw = clean(await get_section_text('About'))
        # Remove the "About" heading word from start
        about = about_raw[5:].strip() if about_raw.startswith('About') else about_raw

        # ── Experience ─────────────────────────────────────────────────────
        experience_blocks = []
        for part in ['Part1', 'Part2', 'Part3']:
            txt = clean(await get_section_text(f'BelowActivityPart'))
            if txt and ('Experience' in txt or 'Education' in txt):
                break
        # Try direct section scrape
        exp_raw = await page.evaluate("""
            (() => {
                const sections = document.querySelectorAll('section');
                for (const s of sections) {
                    if (s.innerText.includes('Experience') && s.innerText.length > 100) {
                        return s.innerText;
                    }
                }
                return '';
            })()
        """)
        if exp_raw:
            experience_blocks = [clean(exp_raw[:2000])]

        # ── Education ──────────────────────────────────────────────────────
        education_blocks = []
        edu_raw = await page.evaluate("""
            (() => {
                const sections = document.querySelectorAll('section');
                for (const s of sections) {
                    if (s.innerText.includes('Education') && s.innerText.length > 50) {
                        return s.innerText;
                    }
                }
                return '';
            })()
        """)
        if edu_raw:
            education_blocks = [clean(edu_raw[:1000])]

        # ── Skills ─────────────────────────────────────────────────────────
        skills_raw = await page.evaluate("""
            (() => {
                const sections = document.querySelectorAll('section');
                for (const s of sections) {
                    if (s.innerText.toLowerCase().includes('skills') && s.innerText.length > 50) {
                        return s.innerText;
                    }
                }
                return '';
            })()
        """)
        skills = [s.strip() for s in (skills_raw or '').split('\n') if s.strip() and len(s.strip()) < 50][:20]

        await browser.close()

    # ── Print summary ──────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PROFILE SUMMARY")
    print("="*60)
    print(f"Name:     {name}")
    print(f"Headline: {headline}")
    print(f"Location: {location}")
    print(f"\nAbout:\n{about[:500] if about else '(none found)'}")
    print(f"\nExperience ({len(experience_blocks)} entries):")
    for i, e in enumerate(experience_blocks):
        print(f"  [{i+1}] {e[:300]}")
    print(f"\nEducation ({len(education_blocks)} entries):")
    for i, e in enumerate(education_blocks):
        print(f"  [{i+1}] {e[:300]}")
    print(f"\nSkills ({len(skills)}):")
    print("  " + ", ".join(skills))

    # ── Save structured result ─────────────────────────────────────────────
    result = {
        "name": name, "headline": headline, "location": location,
        "about": about, "experience": experience_blocks,
        "education": education_blocks, "skills": skills
    }
    out = Path(__file__).parent / 'profile_data.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"\nFull data saved to {out}")


asyncio.run(main())
