#!/usr/bin/env python3
"""
Resume Auto-Tailor
- Uses Claude to return structured JSON (summary, skills order, bullets per section)
- Builds PDF from a fixed HTML template that exactly mirrors resume_preview.html
- Guarantees consistent font size, indentation, and layout on every tailored PDF
"""

import anthropic
import json
import html as hl
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright
import asyncio

config        = dotenv_values(Path.home() / ".env")
ANTHROPIC_KEY = config.get("ANTHROPIC_API_KEY")
_PHONE        = config.get("PHONE", "+353870042809")
_BSC          = config.get("DEGREE_BSC", "Bachelor of Technology in Computer Science\nCMR Institute of Technology — Hyderabad, India\n2020 to 2024")
_MSC          = config.get("DEGREE_MSC", "Master of Science in Cloud Computing\nNational College of Ireland (NCI) — Dublin, Ireland\nSep 2025 to Sep 2026")

# ── Default resume sections (used when Claude's JSON is missing a key) ────────

DEFAULT_TAGLINE = "DevOps / Cloud Engineer"

DEFAULT_SUMMARY = (
    "Cloud Computing MSc student at National College of Ireland (NCI), Dublin, with hands-on "
    "experience in DevOps engineering, AWS cloud deployments, Docker, Kubernetes, CI/CD "
    "automation, and Python development. Currently delivering cloud-native projects involving "
    "containerised microservices, Infrastructure-as-Code using Terraform, and automated deployment "
    "pipelines. Strong understanding of cloud architecture fundamentals and Agile delivery models. "
    "Actively seeking internship, part-time, and graduate opportunities in Cloud Engineering and "
    "DevOps in Dublin. Available for part-time / internship now; full-time from February 2027."
)

DEFAULT_SKILLS = [
    ("Programming Languages", "Python, Bash, SQL"),
    ("Cloud Platforms", "AWS (EC2, S3, IAM, CloudFormation, CloudWatch)"),
    ("Containers & Orchestration", "Docker, Kubernetes"),
    ("CI/CD & Automation", "GitHub Actions, Jenkins"),
    ("Infrastructure as Code", "Terraform, YAML"),
    ("Web & APIs", "RESTful APIs, HTML, CSS, JavaScript"),
    ("Databases", "SQL, PostgreSQL"),
    ("Monitoring & Logging", "Prometheus, Grafana"),
    ("Version Control", "Git, GitHub"),
    ("Operating Systems", "Linux, Windows"),
    ("IDE / Tools", "VS Code, Postman"),
]

DEFAULT_NCI_DESC = (
    "Designed and implemented cloud-native applications as part of MSc coursework, "
    "focusing on containerisation, CI/CD automation, and AWS-based deployments."
)

DEFAULT_NCI_BULLETS = [
    "Developed and deployed cloud-hosted services using AWS (EC2, S3, IAM, CloudFormation).",
    "Built and managed Docker containers and Kubernetes deployments for microservice workloads.",
    "Designed automated GitHub Actions pipelines for build, test, and deployment workflows.",
    "Provisioned infrastructure using Terraform and Kubernetes YAML manifests.",
    "Implemented monitoring and logging for containers using Prometheus and Grafana.",
]

DEFAULT_NCI_ENV = "AWS, Docker, Kubernetes, GitHub Actions, Terraform, Python, Linux, YAML"

DEFAULT_P1_DESC = (
    "Built a 24/7 AI-powered personal assistant Telegram bot integrating Gmail, Google Calendar, "
    "LinkedIn job automation, and Claude AI for natural-language interaction."
)

DEFAULT_P1_BULLETS = [
    "Engineered an automated LinkedIn Easy Apply pipeline using Playwright that searches, filters, and applies to 60+ graduate and DevOps roles in Dublin.",
    "Integrated Gmail IMAP for real-time priority email monitoring and smart alerts.",
    "Connected Google Calendar OAuth for scheduling, event creation, and daily briefings.",
    "Built a Claude AI resume tailoring module that rewrites bullet points to match each job description before applying.",
    "Deployed on Windows with persistent background process management and auto-restart on boot.",
]

DEFAULT_P1_ENV = "Python, Claude AI API, Playwright, Telegram Bot API, Gmail IMAP, Google Calendar API, SQLite, Git, Windows"

DEFAULT_P2_DESC = (
    "Implemented a fully automated CI/CD pipeline using GitHub Actions to deploy a Python web "
    "application to AWS EC2 with zero manual deployment steps."
)

DEFAULT_P2_BULLETS = [
    "Configured a GitHub Actions workflow triggered automatically on every push to the main branch.",
    "Pipeline SSHs into AWS EC2, pulls latest code, installs pip dependencies, and restarts the Gunicorn server via systemctl.",
    "Used GitHub Secrets for secure SSH key and host credential management, eliminating password-based access.",
    "Documented deployment processes and wrote reusable YAML workflow configuration.",
]

DEFAULT_P2_ENV = "GitHub Actions, AWS EC2, Python, Gunicorn, SSH, Git, Linux, YAML"

# Plain-text RESUME used as Claude input context
RESUME = f"""Jaipal Kasireddy
kasireddyjaipal02@gmail.com | {_PHONE} | Dublin, Ireland
linkedin.com/in/jaipal-kasireddy-375a5227b | github.com/Jaipalreddy2
DevOps / Cloud Engineer

PROFESSIONAL SUMMARY
{DEFAULT_SUMMARY}

TECHNICAL SKILLS
{chr(10).join(f'{cat}: {items}' for cat, items in DEFAULT_SKILLS)}

PROFESSIONAL EXPERIENCE

National College of Ireland (NCI), Dublin                          Sep 2025 – Present
Graduate Programme Projects — MSc Cloud Computing
Project Description: {DEFAULT_NCI_DESC}
Responsibilities:
{chr(10).join('• ' + b for b in DEFAULT_NCI_BULLETS)}
Environment: {DEFAULT_NCI_ENV}

PROJECTS

Personal AI Assistant — Telegram Bot                               github.com/Jaipalreddy2/personal-assistant
Tech: {DEFAULT_P1_ENV}
Project Description: {DEFAULT_P1_DESC}
{chr(10).join('• ' + b for b in DEFAULT_P1_BULLETS)}

CI/CD Pipeline — Python App Deployment to AWS EC2                  github.com/Jaipalreddy2/cicd_project1
Tech: {DEFAULT_P2_ENV}
Project Description: {DEFAULT_P2_DESC}
{chr(10).join('• ' + b for b in DEFAULT_P2_BULLETS)}

EDUCATION
{_MSC}
{_BSC}
"""


# ── Claude tailoring ──────────────────────────────────────────────────────────

def tailor_resume_with_claude(job_title, company, job_description):
    """Ask Claude to return structured JSON with tailored resume sections."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    skills_list = "\n".join(f'  "{cat}: {items}"' for cat, items in DEFAULT_SKILLS)

    prompt = f"""You are a professional resume writer. Tailor Jaipal's resume for this job and return ONLY valid JSON.

JOB: {job_title} at {company}

JOB DESCRIPTION:
{job_description if job_description else "No description — tailor based on job title only."}

JAIPAL'S CURRENT RESUME:
{RESUME}

Return a JSON object with EXACTLY these keys (no extras, no markdown, no commentary):
{{
  "tagline": "2-4 word role tagline matching this job (e.g. 'Software Engineer' or 'Cloud / DevOps Engineer')",
  "summary": "3-4 sentence tailored summary paragraph — keep real facts, adjust emphasis",
  "skills": [
    "Category Name: skill1, skill2, skill3",
    ...
  ],
  "nci_desc": "one sentence project description for NCI experience",
  "nci_bullets": ["bullet text without bullet character", ...],
  "nci_env": "comma-separated environment technologies for NCI",
  "p1_desc": "one sentence description for Personal AI Assistant project",
  "p1_bullets": ["bullet text without bullet character", ...],
  "p1_env": "comma-separated environment for Personal AI Assistant",
  "p2_desc": "one sentence description for CI/CD Pipeline project",
  "p2_bullets": ["bullet text without bullet character", ...],
  "p2_env": "comma-separated environment for CI/CD Pipeline"
}}

RULES:
- Keep 5 bullets for NCI, 5 for Personal AI Assistant, 4 for CI/CD Pipeline
- Do NOT invent skills or experience that do not exist in the current resume
- Reorder the skills array to put the most relevant skills for this job first
- Rewrite bullets to use keywords from the job description
- Keep bullet text concise — max 120 characters per bullet
- Return raw JSON only — no ```json``` fences, no explanation"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    # Strip markdown fences if Claude wrapped the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]  # drop ```json line
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


# ── HTML template (exact match to resume_preview.html) ───────────────────────

def _build_resume_html(data: dict) -> str:
    """Build resume HTML from structured data, matching resume_preview.html exactly."""

    tagline  = hl.escape(data.get("tagline", DEFAULT_TAGLINE))
    summary  = hl.escape(data.get("summary", DEFAULT_SUMMARY))

    # Skills table rows
    skill_rows = ""
    raw_skills = data.get("skills", [])
    if not raw_skills:
        raw_skills = [f"{cat}: {items}" for cat, items in DEFAULT_SKILLS]
    for s in raw_skills:
        if ":" in s:
            cat, _, items = s.partition(":")
            skill_rows += f'<tr><td>{hl.escape(cat.strip())}:</td><td>{hl.escape(items.strip())}</td></tr>\n'

    # NCI block
    nci_desc    = hl.escape(data.get("nci_desc", DEFAULT_NCI_DESC))
    nci_bullets = data.get("nci_bullets", DEFAULT_NCI_BULLETS)
    nci_env     = hl.escape(data.get("nci_env", DEFAULT_NCI_ENV))
    nci_li      = "\n".join(f"<li>{hl.escape(b.strip())}</li>" for b in nci_bullets if b.strip())

    # Project 1 — Personal AI Assistant
    p1_desc    = hl.escape(data.get("p1_desc", DEFAULT_P1_DESC))
    p1_bullets = data.get("p1_bullets", DEFAULT_P1_BULLETS)
    p1_env     = hl.escape(data.get("p1_env", DEFAULT_P1_ENV))
    p1_li      = "\n".join(f"<li>{hl.escape(b.strip())}</li>" for b in p1_bullets if b.strip())

    # Project 2 — CI/CD Pipeline
    p2_desc    = hl.escape(data.get("p2_desc", DEFAULT_P2_DESC))
    p2_bullets = data.get("p2_bullets", DEFAULT_P2_BULLETS)
    p2_env     = hl.escape(data.get("p2_env", DEFAULT_P2_ENV))
    p2_li      = "\n".join(f"<li>{hl.escape(b.strip())}</li>" for b in p2_bullets if b.strip())

    # Education lines from env
    edu_lines = ""
    for line in _MSC.strip().splitlines():
        edu_lines += f"{hl.escape(line)}<br>\n"
    edu_lines += "<br>\n"
    for line in _BSC.strip().splitlines():
        edu_lines += f"{hl.escape(line)}<br>\n"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Jaipal Kasireddy — Resume</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: Calibri, "Segoe UI", Arial, sans-serif;
    font-size: 11pt;
    color: #000;
    background: #fff;
  }}
  .page {{
    width: 210mm;
    min-height: 297mm;
    padding: 12mm 15mm 12mm 15mm;
  }}

  /* NAME */
  .name {{
    font-size: 26pt;
    font-weight: 700;
    color: #2e74b5;
    line-height: 1.1;
  }}
  .contact-line {{
    font-size: 11pt;
    color: #000;
    margin-top: 1px;
    line-height: 1.5;
  }}

  /* DIVIDERS */
  hr.divider {{
    border: none;
    border-top: 1px solid #aaa;
    margin: 7px 0 5px 0;
  }}

  /* SECTION HEADINGS */
  h2 {{
    font-size: 13pt;
    font-weight: 700;
    color: #2e74b5;
    border-bottom: 1px solid #2e74b5;
    padding-bottom: 1px;
    margin-top: 9px;
    margin-bottom: 5px;
  }}

  /* SUMMARY */
  .summary {{
    font-size: 11pt;
    line-height: 1.45;
    text-align: justify;
    margin-top: 3px;
  }}

  /* SKILLS TABLE */
  table.skills {{
    width: 100%;
    border-collapse: collapse;
    font-size: 11pt;
    margin-top: 3px;
  }}
  table.skills td {{
    border: none;
    padding: 1px 6px;
    vertical-align: top;
  }}
  table.skills td:first-child {{
    font-weight: 700;
    width: 44%;
    white-space: nowrap;
  }}

  /* EXPERIENCE / PROJECTS */
  .exp-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 7px;
  }}
  .exp-org  {{ font-weight: 700; font-size: 11pt; }}
  .exp-date {{ font-weight: 700; font-size: 11pt; white-space: nowrap; }}
  .exp-role {{ font-style: italic; color: #2e74b5; font-size: 11pt; margin-top: 1px; }}
  .exp-body {{ font-size: 11pt; line-height: 1.45; margin-top: 2px; }}
  .exp-body p {{ margin-top: 4px; }}

  ul.resp {{
    margin-left: 20px;
    margin-top: 4px;
    font-size: 11pt;
    line-height: 1.5;
    list-style-type: disc;
  }}
  ul.resp li {{ margin-bottom: 1px; }}
  .env-line {{ margin-top: 5px; font-size: 11pt; }}

  /* EDUCATION */
  .edu-section {{ margin-top: 5px; font-size: 11pt; line-height: 1.5; }}
</style>
</head>
<body>
<div class="page">

  <!-- HEADER -->
  <div class="name">Jaipal Kasireddy</div>
  <div class="contact-line">Email: kasireddyjaipal02@gmail.com</div>
  <div class="contact-line">Phone: {hl.escape(_PHONE)}</div>
  <div class="contact-line">LinkedIn: linkedin.com/in/jaipal-kasireddy-375a5227b &nbsp;|&nbsp; GitHub: github.com/Jaipalreddy2</div>
  <div class="contact-line">{tagline}</div>

  <hr class="divider">

  <!-- PROFESSIONAL SUMMARY -->
  <h2>Professional Summary</h2>
  <div class="summary">{summary}</div>

  <!-- TECHNICAL SKILLS -->
  <h2>Technical Skills</h2>
  <table class="skills">
    <tbody>
{skill_rows}    </tbody>
  </table>

  <!-- PROFESSIONAL EXPERIENCE -->
  <h2>Professional Experience</h2>

  <div class="exp-header">
    <span class="exp-org">National College of Ireland (NCI), Dublin.</span>
    <span class="exp-date">Sep 2025 – Present</span>
  </div>
  <div class="exp-role">Graduate Programme Projects — MSc Cloud Computing</div>
  <div class="exp-body">
    <p><strong>Project Description:</strong> {nci_desc}</p>
    <p><strong>Responsibilities:</strong></p>
    <ul class="resp">
{nci_li}
    </ul>
    <div class="env-line"><strong>Environment:</strong>&nbsp; {nci_env}</div>
  </div>

  <!-- PROJECTS -->
  <h2>Projects</h2>

  <!-- Project 1 -->
  <div class="exp-header">
    <span class="exp-org">Personal AI Assistant — Telegram Bot</span>
    <span class="exp-date">2025 – Present</span>
  </div>
  <div class="exp-role">Personal Project &nbsp;|&nbsp; github.com/Jaipalreddy2/personal-assistant</div>
  <div class="exp-body">
    <p><strong>Project Description:</strong> {p1_desc}</p>
    <p><strong>Responsibilities:</strong></p>
    <ul class="resp">
{p1_li}
    </ul>
    <div class="env-line"><strong>Environment:</strong>&nbsp; {p1_env}</div>
  </div>

  <!-- Project 2 -->
  <div class="exp-header" style="margin-top:8px;">
    <span class="exp-org">CI/CD Pipeline — Python App Deployment to AWS EC2</span>
    <span class="exp-date">2025</span>
  </div>
  <div class="exp-role">Personal Project &nbsp;|&nbsp; github.com/Jaipalreddy2/cicd_project1</div>
  <div class="exp-body">
    <p><strong>Project Description:</strong> {p2_desc}</p>
    <p><strong>Responsibilities:</strong></p>
    <ul class="resp">
{p2_li}
    </ul>
    <div class="env-line"><strong>Environment:</strong>&nbsp; {p2_env}</div>
  </div>

  <!-- EDUCATION -->
  <h2>Education</h2>
  <div class="edu-section">
{edu_lines}  </div>

</div>
</body>
</html>"""


# ── Public API ────────────────────────────────────────────────────────────────

async def tailor_for_job(job, session_file=None, page=None):
    """Tailor resume for a job. Returns plain-text summary for DB storage."""
    print(f"Tailoring resume for {job['title']} @ {job['company']}...")
    jd = ""
    if page is not None:
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

    raw = tailor_resume_with_claude(job["title"], job["company"], jd)

    # Try to parse as JSON; fall back to raw text for DB
    try:
        data = json.loads(raw)
        # Return plain-text summary for DB storage
        summary = data.get("summary", "")
        tagline = data.get("tagline", DEFAULT_TAGLINE)
        return f"[TAILORED:{job['title']}@{job['company']}]\nTagline: {tagline}\nSummary: {summary}\n---JSON---\n{raw}"
    except json.JSONDecodeError:
        # Claude returned non-JSON — store raw text
        return raw


async def generate_tailored_pdf(tailored_text: str, output_path: str, context=None):
    """Render tailored resume to PDF using the exact resume_preview.html template."""
    # Extract JSON if present in the stored text
    data = {}
    if "---JSON---" in tailored_text:
        _, _, json_part = tailored_text.partition("---JSON---")
        try:
            data = json.loads(json_part.strip())
        except json.JSONDecodeError:
            pass
    else:
        # Legacy plain-text path — try parsing as raw JSON
        try:
            data = json.loads(tailored_text.strip())
        except json.JSONDecodeError:
            pass

    html_content = _build_resume_html(data)
    close_browser = False

    try:
        if context is not None:
            pg = await context.new_page()
        else:
            from playwright.async_api import async_playwright as _ap
            _pw = await _ap().__aenter__()
            browser = await _pw.chromium.launch()
            ctx = await browser.new_context()
            pg = await ctx.new_page()
            close_browser = True

        await pg.set_content(html_content, wait_until="load")
        await pg.pdf(
            path=output_path,
            format="A4",
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
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
    job = {
        "id": "test",
        "title": sys.argv[1] if len(sys.argv) > 1 else "Software Engineer",
        "company": sys.argv[2] if len(sys.argv) > 2 else "Test Company",
        "url": "",
    }

    async def _test():
        text = await tailor_for_job(job)
        print(text[:300])
        out = Path(__file__).parent / "tailored_test.pdf"
        ok = await generate_tailored_pdf(text, str(out))
        print(f"PDF generated: {ok} → {out}")

    asyncio.run(_test())
