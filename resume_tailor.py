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
Jaipal Kasireddy
kasireddyjaipal02@gmail.com | {_PHONE} | Dublin, Ireland
linkedin.com/in/jaipal-kasireddy-375a5227b | github.com/Jaipalreddy2
DevOps / Cloud Engineer

PROFESSIONAL SUMMARY
Cloud Computing MSc student at National College of Ireland (NCI), Dublin, with hands-on
experience in DevOps engineering, AWS cloud deployments, Docker, Kubernetes, CI/CD
automation, and Python development. Currently delivering cloud-native projects involving
containerised microservices, Infrastructure-as-Code using Terraform, and automated deployment
pipelines. Strong understanding of cloud architecture fundamentals and Agile delivery models.
Actively seeking internship, part-time, and graduate opportunities in Cloud Engineering and
DevOps in Dublin. Available for part-time / internship now; full-time from February 2027.

TECHNICAL SKILLS
Programming Languages : Python, Bash, SQL
Cloud Platforms       : AWS (EC2, S3, IAM, CloudFormation, CloudWatch)
Containers & Orch.    : Docker, Kubernetes
CI/CD & Automation    : GitHub Actions, Jenkins
Infrastructure as Code: Terraform, YAML
Web & APIs            : RESTful APIs, HTML, CSS, JavaScript
Databases             : SQL, PostgreSQL
Monitoring & Logging  : Prometheus, Grafana
Version Control       : Git, GitHub
Operating Systems     : Linux, Windows
IDE / Tools           : VS Code, Postman

PROFESSIONAL EXPERIENCE

National College of Ireland (NCI), Dublin                          Sep 2025 – Present
Graduate Programme Projects — MSc Cloud Computing
Project Description: Designed and implemented cloud-native applications as part of MSc
coursework, focusing on containerisation, CI/CD automation, and AWS-based deployments.
Responsibilities:
• Developed and deployed cloud-hosted services using AWS (EC2, S3, IAM, CloudFormation).
• Built and managed Docker containers and Kubernetes deployments for microservice workloads.
• Designed automated GitHub Actions pipelines for build, test, and deployment workflows.
• Provisioned infrastructure using Terraform and Kubernetes YAML manifests.
• Implemented monitoring and logging for containers using Prometheus and Grafana.
Environment: AWS, Docker, Kubernetes, GitHub Actions, Terraform, Python, Linux, YAML

PROJECTS

Personal AI Assistant — Telegram Bot                               github.com/Jaipalreddy2/personal-assistant
Tech: Python, Claude AI API, Playwright, Telegram Bot API, Gmail IMAP, Google Calendar API, SQLite
• Built a 24/7 personal assistant Telegram bot powered by Claude AI handling natural-language
  requests, Gmail monitoring, Google Calendar management, and LinkedIn job automation.
• Engineered an automated LinkedIn Easy Apply pipeline using Playwright that searches, filters,
  and applies to 60+ graduate/DevOps roles in Dublin with AI-tailored resumes per job.
• Integrated Gmail IMAP for real-time email alerts and Google Calendar OAuth for scheduling.
• Deployed on Windows with persistent background process management and auto-restart on boot.

CI/CD Pipeline — Python App Deployment to AWS EC2                  github.com/Jaipalreddy2/cicd_project1
Tech: GitHub Actions, AWS EC2, Python, Gunicorn, SSH, Git, Linux
• Implemented a fully automated GitHub Actions CI/CD pipeline triggered on every push to main.
• Pipeline SSHs into an AWS EC2 instance, pulls the latest code, installs dependencies via pip,
  and restarts the Gunicorn application server using systemctl — zero manual deployment steps.
• Used GitHub Secrets for secure SSH key and host management, eliminating password-based access.

EDUCATION
{_MSC}
{_BSC}
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


async def tailor_for_job(job, session_file=None, page=None):
    """Full pipeline: optionally scrape JD (reusing existing page) → tailor → return text."""
    print(f"Tailoring resume for {job['title']} @ {job['company']}...")
    jd = ""
    if page is not None:
        # Reuse the already-open browser page — no second LinkedIn request
        try:
            desc_el = (
                await page.query_selector(".jobs-description__content") or
                await page.query_selector("#job-details") or
                await page.query_selector(".description__text")
            )
            if desc_el:
                jd = (await desc_el.inner_text()).strip()[:3000]
        except Exception:
            pass
    # If no JD scraped, tailor from title+company alone (no extra browser)
    tailored = tailor_resume_with_claude(job["title"], job["company"], jd)
    return tailored


def _resume_text_to_html(text: str) -> str:
    """Convert Claude's plain-text tailored resume into a styled HTML page."""
    import html as hl
    lines = text.strip().split('\n')
    out = []
    in_ul = False
    is_first_line = True

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            if in_ul:
                out.append('</ul>')
                in_ul = False
            out.append('<div class="gap"></div>')
            continue

        # Close open bullet list before any non-bullet line
        is_bullet = stripped.startswith(('•', '-', '*')) and len(stripped) > 2

        if not is_bullet and in_ul:
            out.append('</ul>')
            in_ul = False

        if is_first_line:
            out.append(f'<div class="name">{hl.escape(stripped)}</div>')
            is_first_line = False
            continue

        if is_bullet:
            if not in_ul:
                out.append('<ul>')
                in_ul = True
            content = hl.escape(stripped.lstrip('•-* ').strip())
            out.append(f'<li>{content}</li>')
            continue

        # Section header: all-caps word(s), length > 3
        if stripped == stripped.upper() and len(stripped) > 3 and stripped.replace(' ','').isalpha():
            out.append(f'<h2>{hl.escape(stripped)}</h2>')
            continue

        # Contact / link lines near the top (contain | or @ or linkedin/github)
        low = stripped.lower()
        if '|' in stripped or '@' in stripped or 'linkedin' in low or 'github' in low:
            out.append(f'<p class="contact">{hl.escape(stripped)}</p>')
            continue

        # Bold label lines: "Label: value" or "Label — value"
        if ':' in stripped and stripped.index(':') < 35:
            label, _, rest = stripped.partition(':')
            out.append(f'<p><strong>{hl.escape(label)}:</strong>{hl.escape(rest)}</p>')
            continue

        out.append(f'<p>{hl.escape(stripped)}</p>')

    if in_ul:
        out.append('</ul>')

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
  body{{font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000;margin:0;padding:14mm 15mm}}
  .name{{font-size:22pt;font-weight:700;color:#2e74b5;margin-bottom:2px}}
  .contact{{font-size:10.5pt;margin:1px 0;line-height:1.4}}
  h2{{font-size:12pt;font-weight:700;color:#2e74b5;border-bottom:1px solid #2e74b5;
      margin:9px 0 3px 0;padding-bottom:1px}}
  p{{margin:2px 0;font-size:11pt;line-height:1.4}}
  ul{{margin:3px 0 3px 20px}}
  li{{font-size:11pt;line-height:1.5;margin-bottom:1px}}
  .gap{{height:3px}}
</style></head><body>{''.join(out)}</body></html>"""


async def generate_tailored_pdf(tailored_text: str, output_path: str, context=None):
    """Render the tailored resume text to a PDF file.
    Re-uses an existing Playwright browser context if provided (avoids nested instances)."""
    html_content = _resume_text_to_html(tailored_text)
    close_browser = False

    try:
        if context is not None:
            pg = await context.new_page()
        else:
            from playwright.async_api import async_playwright as _ap
            _pw = await _ap().__aenter__()
            browser = await _pw.chromium.launch()
            context = await browser.new_context()
            pg = await context.new_page()
            close_browser = True

        await pg.set_content(html_content, wait_until='load')
        await pg.pdf(
            path=output_path,
            format='A4',
            margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'},
            print_background=False,
        )
        await pg.close()
        if close_browser:
            await browser.close()
        return True
    except Exception as e:
        print(f"  PDF generation error: {e}")
        return False


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
