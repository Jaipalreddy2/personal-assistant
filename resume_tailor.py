#!/usr/bin/env python3
"""
Resume Auto-Tailor
- Fetches job description from LinkedIn
- Uses Claude to rewrite resume bullets to match the role
- Returns tailored resume text to send via Telegram
"""

import anthropic
import requests
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright
import asyncio

config        = dotenv_values(Path.home() / ".env")
ANTHROPIC_KEY = config.get("ANTHROPIC_API_KEY")
_PHONE        = config.get("PHONE", "")
_BSC          = config.get("DEGREE_BSC", "")
_MSC          = config.get("DEGREE_MSC", "")

RESUME = f"""
Jaipal Kasi Reddy
kasireddyjaipal02@gmail.com | {_PHONE} | Dublin, Ireland
linkedin.com/in/jaipal-kasireddy-375a5227b | github.com/Jaipalreddy2

PROFILE
MSc Cloud Computing student at National College of Ireland (NCI), Dublin. Passionate about
building scalable, reliable, and secure cloud infrastructure. Seeking graduate and internship
roles in Cloud Engineering, DevOps, and Software Development. Available for part-time work
during studies and full-time from February 2027.

EDUCATION
{_MSC}
{_BSC}

PROJECTS
Personal AI Assistant Bot  (Python · Telegram · Playwright · Claude AI · LinkedIn API)
• Automated LinkedIn Easy Apply pipeline: searches 60+ DevOps/Cloud roles and auto-applies to
  fresher and graduate positions in Dublin
• Integrated Gmail IMAP, Google Calendar, and Telegram Bot API for a 24/7 personal assistant
• Resume tailoring module uses Claude AI to rewrite bullet points matching each job description
• Deployed on Windows with auto-start via Startup folder and PYTHONUTF8 compatibility fixes

TODO: Add university projects (e.g. Cloud deployment project, Kubernetes lab, etc.)

TECHNICAL SKILLS
Cloud:      AWS (EC2, S3, IAM, CloudFormation — actively learning)
DevOps:     Docker, Kubernetes, CI/CD Pipelines (GitHub Actions)
OS:         Linux (command line, Bash scripting)
Programming: Python, SQL
Tools:      Git, GitHub

CERTIFICATIONS
TODO: Add AWS Cloud Practitioner, CKA, or other certs if completed

INTERESTS / OPEN TO
Cloud Engineer | DevOps Engineer | Graduate Programme | Platform Engineer | IT Systems
Dublin on-site · Hybrid · Remote
"""


async def fetch_job_description(url, session_file):
    """Scrape job description from LinkedIn job page."""
    try:
        import json
        cookies = json.loads(Path(session_file).read_text()) if Path(session_file).exists() else []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            if cookies:
                cookie_list = cookies["cookies"] if isinstance(cookies, dict) and "cookies" in cookies else cookies
                await context.add_cookies(cookie_list)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Try to expand "Show more" for full description
            try:
                btn = await page.query_selector("button[aria-label*='more']")
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            desc_el = (
                await page.query_selector(".jobs-description__content") or
                await page.query_selector(".job-details-jobs-unified-top-card__job-insight") or
                await page.query_selector("#job-details") or
                await page.query_selector(".description__text")
            )
            desc = (await desc_el.inner_text()).strip() if desc_el else ""
            await browser.close()
            return desc[:3000]  # cap at 3k chars for Claude
    except Exception as e:
        print(f"Could not fetch job description: {e}")
        return ""


def tailor_resume_with_claude(job_title, company, job_description):
    """Ask Claude to rewrite resume bullets to match the job."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""You are a professional resume writer. Tailor Jaipal's resume for this specific job.

JOB: {job_title} at {company}

JOB DESCRIPTION:
{job_description if job_description else "No description available — tailor based on job title."}

JAIPAL'S CURRENT RESUME:
{RESUME}

INSTRUCTIONS:
1. Keep the same structure and all real experience — do NOT invent anything
2. Rewrite bullet points to use keywords from the job description
3. Reorder skills to put the most relevant ones first
4. Adjust the summary/profile emphasis to match what this company wants
5. Keep it concise — max 1 page worth of content

Return ONLY the tailored resume text, no commentary."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


async def tailor_for_job(job, session_file):
    """Full pipeline: fetch JD → tailor → return text."""
    print(f"Tailoring resume for {job['title']} @ {job['company']}...")
    jd = await fetch_job_description(job["url"], session_file)
    tailored = tailor_resume_with_claude(job["title"], job["company"], jd)
    return tailored


if __name__ == "__main__":
    import sys
    # Quick test
    job = {
        "title": sys.argv[1] if len(sys.argv) > 1 else "Software Developer .NET",
        "company": sys.argv[2] if len(sys.argv) > 2 else "Test Company",
        "url": sys.argv[3] if len(sys.argv) > 3 else ""
    }
    session = Path(__file__).parent / "linkedin_session.json"
    result = asyncio.run(tailor_for_job(job, str(session)))
    print(result)
