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
