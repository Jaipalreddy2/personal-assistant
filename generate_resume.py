#!/usr/bin/env python3
"""Generate a professional PDF resume — renders HTML via Playwright (Chromium)."""
import sys, io, asyncio, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright
from dotenv import dotenv_values
from pathlib import Path

config = dotenv_values(Path.home() / ".env")
PHONE  = config.get("PHONE", "+353 870042809")
OUT    = Path(__file__).parent / "Jaipal_Kasi_Reddy_Resume.pdf"


def build_html():
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
    font-size: 8.8pt;
    color: #1a1a2e;
    background: #fff;
    width: 210mm;
    min-height: 297mm;
    display: flex;
    flex-direction: column;
  }}

  /* ──────────────────── TOP HEADER ──────────────────── */
  .header {{
    background: linear-gradient(135deg, #0f3770 0%, #1a5ba6 100%);
    padding: 10mm 12mm 9mm 12mm;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }}
  .header-left {{ flex: 1; }}
  .header-name {{
    font-size: 24pt;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.5px;
    line-height: 1;
    margin-bottom: 1.5mm;
  }}
  .header-role {{
    font-size: 10.5pt;
    font-weight: 500;
    color: #a8d0f5;
    letter-spacing: 0.2px;
    margin-bottom: 3.5mm;
  }}
  .header-keywords {{
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
  }}
  .hkw {{
    background: rgba(255,255,255,0.12);
    color: #d4e9ff;
    font-size: 7pt;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 20px;
    border: 1px solid rgba(168,208,245,0.30);
    letter-spacing: 0.2px;
  }}
  .header-contact {{
    text-align: right;
    flex-shrink: 0;
    margin-left: 8mm;
  }}
  .hc-item {{
    font-size: 7.8pt;
    color: #c0daee;
    line-height: 1.7;
  }}
  .hc-item span {{
    color: #fff;
    font-weight: 500;
  }}

  /* ──────────────────── BODY: TWO COLUMNS ──────────────────── */
  .body {{
    display: flex;
    flex: 1;
  }}

  /* Left column */
  .left {{
    width: 62mm;
    background: #f4f7fb;
    padding: 7mm 6mm 8mm 7mm;
    border-right: 1px solid #dde6f2;
    flex-shrink: 0;
  }}

  /* Right column */
  .right {{
    flex: 1;
    padding: 7mm 9mm 8mm 8mm;
  }}

  /* ── Section heading ── */
  .sec-title {{
    font-size: 6.8pt;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: #0f3770;
    padding-bottom: 1.5mm;
    border-bottom: 1.8px solid #0f3770;
    margin-bottom: 3.5mm;
  }}
  .section {{ margin-bottom: 5.5mm; }}

  /* ── Left: skill groups ── */
  .skill-group {{ margin-bottom: 3.5mm; }}
  .skill-cat {{
    font-size: 7.5pt;
    font-weight: 600;
    color: #0f3770;
    margin-bottom: 1.5mm;
  }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 2px; }}
  .tag {{
    background: #e2ecf8;
    color: #1a3a6e;
    font-size: 6.8pt;
    font-weight: 500;
    padding: 1.5px 6px;
    border-radius: 3px;
    line-height: 1.6;
  }}
  .tag.highlight {{
    background: #0f3770;
    color: #fff;
  }}

  /* ── Left: education ── */
  .edu-item {{ margin-bottom: 3.5mm; }}
  .edu-deg {{
    font-size: 8.5pt;
    font-weight: 600;
    color: #1a1a2e;
    line-height: 1.3;
  }}
  .edu-uni {{
    font-size: 7.5pt;
    color: #4b6080;
    line-height: 1.4;
    margin-top: 0.5mm;
  }}
  .edu-yr {{
    font-size: 7pt;
    color: #7890a8;
    margin-top: 0.5mm;
    font-style: italic;
  }}

  /* ── Left: open to ── */
  .role-tag {{
    display: inline-block;
    background: #fff;
    border: 1px solid #bed3ec;
    color: #1a3a6e;
    font-size: 7pt;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 10px;
    margin: 1.5px 1px;
    line-height: 1.5;
  }}

  /* ── Right: summary ── */
  .summary-text {{
    font-size: 8.8pt;
    color: #2c3344;
    line-height: 1.6;
  }}
  .summary-text strong {{ color: #0f3770; font-weight: 600; }}

  /* ── Right: project cards ── */
  .proj {{
    background: #fff;
    border: 1px solid #dde6f2;
    border-left: 3.5px solid #0f3770;
    border-radius: 0 5px 5px 0;
    padding: 3.5mm 4mm;
    margin-bottom: 3.5mm;
  }}
  .proj:last-child {{ margin-bottom: 0; }}
  .proj-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1mm;
  }}
  .proj-title {{
    font-size: 9.2pt;
    font-weight: 700;
    color: #0f3770;
    line-height: 1.25;
    flex: 1;
  }}
  .proj-link {{
    font-size: 7pt;
    color: #6b84a0;
    text-align: right;
    margin-left: 3mm;
    white-space: nowrap;
  }}
  .proj-stack {{
    font-size: 7.5pt;
    color: #4b6080;
    font-style: italic;
    margin-bottom: 2mm;
    line-height: 1.4;
  }}
  .proj ul {{ list-style: none; padding: 0; }}
  .proj ul li {{
    font-size: 8.2pt;
    color: #2c3344;
    line-height: 1.55;
    padding-left: 10px;
    position: relative;
    margin-bottom: 1.5px;
  }}
  .proj ul li::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 5.5px;
    width: 4.5px;
    height: 4.5px;
    border-radius: 50%;
    background: #0f3770;
  }}

  /* ── availability ── */
  .avail-box {{
    background: #f0f6ff;
    border: 1px solid #c4d8f0;
    border-radius: 5px;
    padding: 3mm 4mm;
  }}
  .avail-row {{
    display: flex;
    font-size: 8.2pt;
    line-height: 1.5;
    margin-bottom: 0.5mm;
  }}
  .avail-row:last-child {{ margin-bottom: 0; }}
  .al {{ font-weight: 600; color: #0f3770; min-width: 22mm; flex-shrink: 0; }}
  .av {{ color: #2c3344; }}

  /* ── footer ── */
  .footer {{
    background: #0f3770;
    text-align: center;
    padding: 2mm;
    font-size: 7pt;
    color: rgba(255,255,255,0.65);
    letter-spacing: 0.3px;
  }}
</style>
</head>
<body>

<!-- ═══  HEADER  ═══ -->
<div class="header">
  <div class="header-left">
    <div class="header-name">JAIPAL KASI REDDY</div>
    <div class="header-role">Cloud &amp; DevOps Engineer</div>
    <div class="header-keywords">
      <span class="hkw">AWS &amp; Cloud Infrastructure</span>
      <span class="hkw">Docker &amp; Kubernetes</span>
      <span class="hkw">CI/CD Pipelines</span>
      <span class="hkw">Terraform &amp; Ansible</span>
      <span class="hkw">Python Automation</span>
      <span class="hkw">Prometheus &amp; ELK</span>
    </div>
  </div>
  <div class="header-contact">
    <div class="hc-item"><span>{PHONE}</span></div>
    <div class="hc-item"><span>kasireddyjaipal02@gmail.com</span></div>
    <div class="hc-item"><span>Dublin, Ireland</span></div>
    <div class="hc-item">linkedin.com/in/<span>jaipal-kasireddy-375a5227b</span></div>
    <div class="hc-item">github.com/<span>Jaipalreddy2</span></div>
  </div>
</div>

<!-- ═══  BODY  ═══ -->
<div class="body">

  <!-- ── LEFT COLUMN ── -->
  <div class="left">

    <div class="section">
      <div class="sec-title">Cloud &amp; Infrastructure</div>
      <div class="skill-group">
        <div class="skill-cat">AWS</div>
        <div class="tags">
          <span class="tag highlight">EC2</span><span class="tag highlight">S3</span>
          <span class="tag">IAM</span><span class="tag">VPC</span>
          <span class="tag">Lambda</span><span class="tag">CloudFormation</span><span class="tag">RDS</span>
        </div>
      </div>
      <div class="skill-group">
        <div class="skill-cat">Other Cloud</div>
        <div class="tags">
          <span class="tag">Azure (fundamentals)</span>
          <span class="tag">GCP (fundamentals)</span>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="sec-title">DevOps &amp; CI/CD</div>
      <div class="tags">
        <span class="tag highlight">Docker</span>
        <span class="tag highlight">Kubernetes</span>
        <span class="tag highlight">GitHub Actions</span>
        <span class="tag">Jenkins</span>
        <span class="tag">GitLab CI</span>
        <span class="tag">Terraform</span>
        <span class="tag">Ansible</span>
        <span class="tag">Nginx</span>
        <span class="tag">Gunicorn</span>
        <span class="tag">systemd</span>
      </div>
    </div>

    <div class="section">
      <div class="sec-title">Monitoring &amp; Observability</div>
      <div class="tags">
        <span class="tag highlight">Prometheus</span>
        <span class="tag highlight">Grafana</span>
        <span class="tag">Elasticsearch</span>
        <span class="tag">Logstash</span>
        <span class="tag">Kibana</span>
      </div>
    </div>

    <div class="section">
      <div class="sec-title">Programming &amp; Tools</div>
      <div class="tags">
        <span class="tag highlight">Python</span>
        <span class="tag">Bash</span>
        <span class="tag">SQL</span>
        <span class="tag">REST APIs</span>
        <span class="tag">Linux (RHEL/Ubuntu)</span>
        <span class="tag">Git / GitHub</span>
        <span class="tag">PostgreSQL</span>
        <span class="tag">MongoDB</span>
        <span class="tag">Redis</span>
      </div>
    </div>

    <div class="section">
      <div class="sec-title">Education</div>
      <div class="edu-item">
        <div class="edu-deg">MSc Cloud Computing</div>
        <div class="edu-uni">National College of Ireland<br>Dublin, Ireland</div>
        <div class="edu-yr">2026 – 2027 (expected)</div>
      </div>
      <div class="edu-item">
        <div class="edu-deg">B.Tech Computer Science &amp; Engineering</div>
        <div class="edu-uni">CMR Institute of Technology<br>Hyderabad, India</div>
        <div class="edu-yr">2020 – 2024</div>
      </div>
    </div>

    <div class="section">
      <div class="sec-title">Open To</div>
      <span class="role-tag">Cloud Engineer</span>
      <span class="role-tag">DevOps Engineer</span>
      <span class="role-tag">Graduate Programme</span>
      <span class="role-tag">SRE</span>
      <span class="role-tag">Platform Engineer</span>
    </div>

  </div><!-- /left -->

  <!-- ── RIGHT COLUMN ── -->
  <div class="right">

    <div class="section">
      <div class="sec-title">Professional Summary</div>
      <div class="summary-text">
        Graduate Cloud &amp; DevOps Engineer with hands-on experience building
        <strong>CI/CD pipelines</strong>, containerised workloads, and cloud infrastructure on <strong>AWS</strong>.
        Currently completing an <strong>MSc in Cloud Computing at NCI Dublin</strong>.
        Demonstrated ability to automate deployments end-to-end — from GitHub commit to a live EC2 instance — using
        GitHub Actions, Docker, Gunicorn, and systemd.
        Proficient in <strong>Terraform, Ansible, Kubernetes, Jenkins, Prometheus</strong>, and Python.
        Actively seeking graduate Cloud / DevOps / SRE roles in Dublin with immediate availability.
      </div>
    </div>

    <div class="section">
      <div class="sec-title">Projects</div>

      <div class="proj">
        <div class="proj-top">
          <div class="proj-title">CI/CD Pipeline — Automated Deployment to AWS EC2</div>
          <div class="proj-link">github.com/Jaipalreddy2/cicd_project1</div>
        </div>
        <div class="proj-stack">GitHub Actions &nbsp;·&nbsp; AWS EC2 &nbsp;·&nbsp; Python &nbsp;·&nbsp; Gunicorn &nbsp;·&nbsp; systemd &nbsp;·&nbsp; SSH &nbsp;&nbsp;|&nbsp;&nbsp; 2025</div>
        <ul>
          <li>Designed an end-to-end CI/CD pipeline: every push to <em>main</em> triggers a GitHub Actions workflow that SSHs into AWS EC2, pulls the latest code, installs dependencies, and restarts the app via <strong>systemd</strong> — zero manual steps</li>
          <li>Secured the pipeline using <strong>GitHub Secrets</strong> for EC2 host address and private SSH key; used <em>appleboy/ssh-action</em> for robust remote execution</li>
          <li>Configured the Python web app as a persistent <strong>systemd service</strong> with automatic restart on failure and Gunicorn for production-grade serving</li>
        </ul>
      </div>

      <div class="proj">
        <div class="proj-top">
          <div class="proj-title">Personal AI Assistant — Telegram Bot &amp; LinkedIn Automation</div>
          <div class="proj-link">github.com/Jaipalreddy2/personal-assistant</div>
        </div>
        <div class="proj-stack">Python 3.14 &nbsp;·&nbsp; Playwright &nbsp;·&nbsp; Claude AI API &nbsp;·&nbsp; Telegram Bot API &nbsp;·&nbsp; SQLite &nbsp;·&nbsp; asyncio &nbsp;&nbsp;|&nbsp;&nbsp; 2025</div>
        <ul>
          <li>Built a 24/7 Telegram bot integrating <strong>Gmail IMAP</strong>, Google Calendar, and <strong>LinkedIn Easy Apply automation</strong> using Playwright Chromium — all orchestrated by Claude AI for context-aware responses</li>
          <li>Engineered a complete job pipeline: scrapes LinkedIn for Cloud/DevOps roles in Dublin, tailors resume per job via <strong>Claude LLM prompt engineering</strong>, tracks every application in SQLite with status history</li>
          <li>Deployed on Windows with async event loop management, PID-based process isolation, auto session refresh, and reboot persistence</li>
        </ul>
      </div>

      <div class="proj">
        <div class="proj-top">
          <div class="proj-title">Cloud-Native Smart Parking Slot Booking System</div>
          <div class="proj-link">MSc Capstone — 2024</div>
        </div>
        <div class="proj-stack">AWS &nbsp;·&nbsp; Docker &nbsp;·&nbsp; Kubernetes &nbsp;·&nbsp; Python &nbsp;·&nbsp; PostgreSQL (RDS) &nbsp;·&nbsp; REST API</div>
        <ul>
          <li>Architected a <strong>microservices-based</strong> parking booking platform on AWS: Dockerised services orchestrated by Kubernetes with auto-scaling, health checks, and rolling updates</li>
          <li>Implemented RESTful APIs in Python, provisioned <strong>PostgreSQL on Amazon RDS</strong>, and built a CI/CD pipeline for automated container builds and cluster deployments</li>
        </ul>
      </div>

    </div>

    <div class="section">
      <div class="sec-title">Availability</div>
      <div class="avail-box">
        <div class="avail-row">
          <span class="al">Immediate:</span>
          <span class="av">Part-time &nbsp;(Dublin on-site / Hybrid / Remote)</span>
        </div>
        <div class="avail-row">
          <span class="al">From Feb 2027:</span>
          <span class="av">Full-time after MSc completion</span>
        </div>
        <div class="avail-row">
          <span class="al">Work Auth:</span>
          <span class="av">Student visa (20 hrs/week term-time, full-time during breaks)</span>
        </div>
      </div>
    </div>

  </div><!-- /right -->
</div><!-- /body -->

<div class="footer">
  Jaipal Kasi Reddy &nbsp;|&nbsp; kasireddyjaipal02@gmail.com &nbsp;|&nbsp; Dublin, Ireland &nbsp;|&nbsp; linkedin.com/in/jaipal-kasireddy-375a5227b
</div>

</body>
</html>"""


async def render():
    html_path = Path(tempfile.mktemp(suffix=".html"))
    html_path.write_text(build_html(), encoding="utf-8")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(f"file:///{html_path}", wait_until="networkidle")
            await page.wait_for_timeout(1500)
            await page.pdf(
                path=str(OUT),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            await browser.close()
    finally:
        html_path.unlink(missing_ok=True)
    print(f"Resume saved: {OUT}")


if __name__ == "__main__":
    asyncio.run(render())
