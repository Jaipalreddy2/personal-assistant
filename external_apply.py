#!/usr/bin/env python3
"""
External ATS auto-apply handlers.
Supported: Greenhouse, Lever, Workday, SmartRecruiters, Ashby, BambooHR, Recruitee, generic.

Called from linkedin_apply.py when Easy Apply redirects to a third-party site.
"""
import asyncio
import re
from pathlib import Path
from dotenv import dotenv_values

config    = dotenv_values(Path.home() / ".env")
RESUME_PDF = Path(__file__).parent / "Jaipal_Kasi_Reddy_Resume.pdf"

# ── Applicant info ─────────────────────────────────────────────────────────────
INFO = {
    "first":    "Jaipal",
    "last":     "Kasi Reddy",
    "name":     "Jaipal Kasireddy",
    "email":    config.get("GMAIL_ADDRESS", "kasireddyjaipal02@gmail.com"),
    "phone":    config.get("PHONE", "+353870042809").replace(" ", ""),
    "linkedin": "https://www.linkedin.com/in/jaipal-kasireddy-375a5227b",
    "github":   "https://github.com/Jaipalreddy2",
    "website":  "https://github.com/Jaipalreddy2",
    "city":     "Dublin",
    "country":  "Ireland",
    "location": "Dublin, Ireland",
    "zip":      "D01",
}

COVER_LETTER = (
    "Dear Hiring Manager,\n\n"
    "I am applying for the {title} position at {company}. "
    "I am a Cloud & DevOps Engineer currently completing my MSc in Cloud Computing at the "
    "National College of Ireland, Dublin.\n\n"
    "I have hands-on experience with AWS (EC2, S3, IAM, VPC, Lambda), Docker, Kubernetes, "
    "CI/CD pipelines using GitHub Actions, Terraform, Ansible, Prometheus/Grafana, and Python automation. "
    "I recently built an end-to-end CI/CD pipeline deploying Python apps to AWS EC2 using GitHub Actions "
    "and systemd, and engineered a 24/7 AI assistant integrating Playwright, Claude AI, and LinkedIn automation.\n\n"
    "I am based in Dublin, available part-time immediately and full-time from February 2027. "
    "I am eligible to work in Ireland on a student visa (20 hrs/week during term, full-time during breaks).\n\n"
    "I look forward to discussing how my skills can contribute to your team.\n\n"
    "Best regards,\n"
    "Jaipal Kasireddy\n"
    "{phone} | kasireddyjaipal02@gmail.com\n"
    "Dublin, Ireland | linkedin.com/in/jaipal-kasireddy-375a5227b"
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def detect_ats(url: str) -> str:
    u = url.lower()
    if "greenhouse.io" in u:       return "greenhouse"
    if "lever.co" in u:            return "lever"
    if "myworkdayjobs.com" in u or "wd3.myworkdayjobs" in u: return "workday"
    if "smartrecruiters.com" in u: return "smartrecruiters"
    if "ashbyhq.com" in u:         return "ashby"
    if "bamboohr.com" in u:        return "bamboohr"
    if "recruitee.com" in u:       return "recruitee"
    if "icims.com" in u:           return "icims"
    if "taleo.net" in u:           return "taleo"
    if "jobvite.com" in u:         return "jobvite"
    if "workable.com" in u:        return "workable"
    return "generic"


async def _fill(page, selector, value):
    """Fill a single field if it exists."""
    try:
        el = await page.query_selector(selector)
        if el:
            await el.click()
            await page.wait_for_timeout(150)
            await el.fill(str(value))
            return True
    except Exception:
        pass
    return False


async def _fill_any(page, selectors: list, value: str):
    """Try selectors in order, fill the first found."""
    for sel in selectors:
        if await _fill(page, sel, value):
            return True
    return False


async def _upload_resume(page) -> bool:
    """Attach the PDF resume to any file input on the page."""
    if not RESUME_PDF.exists():
        print("  [ext] Resume PDF missing!")
        return False
    try:
        inputs = await page.query_selector_all("input[type='file']")
        for inp in inputs:
            try:
                await inp.set_input_files(str(RESUME_PDF))
                await page.wait_for_timeout(1200)
                print("  [ext] Uploaded resume PDF")
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _click_upload_button_then_input(page):
    """Some forms show a styled upload button — click it, wait for file dialog,
    then set files on the hidden input."""
    try:
        # Trigger any upload button
        upload_btn = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, label'));
            for (const b of btns) {
                const t = (b.innerText || b.getAttribute('aria-label') || '').toLowerCase();
                if (t.includes('upload') || t.includes('attach') || t.includes('resume') || t.includes('cv')) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if upload_btn:
            await page.wait_for_timeout(800)
        return await _upload_resume(page)
    except Exception:
        return False


async def _answer_yes_no(page):
    """Answer yes/no/authorization/sponsorship questions automatically."""
    try:
        await page.evaluate("""() => {
            // Click "Yes" radio buttons for work authorization type questions
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                const lbl = document.querySelector('label[for="' + r.id + '"]');
                const txt = (lbl?.innerText || r.value || '').trim().toLowerCase();
                if (txt === 'yes' || txt === 'true') r.click();
            });
        }""")
        await page.wait_for_timeout(300)

        # Handle <select> dropdowns with yes/no choices
        selects = await page.query_selector_all("select")
        for sel in selects:
            try:
                opts = await sel.evaluate(
                    "el => Array.from(el.options).map(o => ({v: o.value, t: o.text.trim().toLowerCase()}))"
                )
                picked = False
                for o in opts:
                    # Prefer "yes" or "no sponsorship required"
                    if o["t"] in ("yes", "true", "i am authorized to work",
                                  "no, i do not require sponsorship",
                                  "no sponsorship", "citizen", "permanent resident",
                                  "i do not require sponsorship"):
                        await sel.select_option(o["v"])
                        picked = True
                        break
                if not picked:
                    # For unknown dropdowns pick first non-empty option
                    for o in opts:
                        if o["v"] and o["t"] not in ("", "select", "please select", "choose"):
                            await sel.select_option(o["v"])
                            break
            except Exception:
                continue
    except Exception:
        pass


async def _fill_cover_letter(page, job):
    """Fill cover letter textarea if present."""
    try:
        areas = await page.query_selector_all("textarea")
        for area in areas:
            try:
                placeholder = (await area.get_attribute("placeholder") or "").lower()
                aria_label  = (await area.get_attribute("aria-label") or "").lower()
                label_el    = await area.evaluate_handle(
                    "el => { const id = el.id; return id ? document.querySelector('label[for=\"'+id+'\"]') : null; }"
                )
                label_text = ""
                try:
                    label_text = (await label_el.inner_text()).lower()
                except Exception:
                    pass

                if any(k in (placeholder + aria_label + label_text)
                       for k in ("cover letter", "cover note", "motivation", "letter")):
                    cl = COVER_LETTER.format(
                        title=job.get("title", "the role"),
                        company=job.get("company", "your company"),
                        phone=INFO["phone"]
                    )
                    await area.fill(cl)
                    print("  [ext] Filled cover letter")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _submit(page) -> bool:
    """Click the submit/apply button."""
    try:
        clicked = await page.evaluate("""() => {
            const keywords = ['submit application', 'submit', 'apply now', 'apply',
                              'send application', 'complete application'];
            const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
            for (const kw of keywords) {
                for (const btn of btns) {
                    const t = (btn.innerText || btn.value || btn.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (t === kw || t.includes(kw)) {
                        if (!btn.disabled) { btn.click(); return kw; }
                    }
                }
            }
            return null;
        }""")
        if clicked:
            await page.wait_for_timeout(3000)
            print(f"  [ext] Clicked: {clicked}")
            return True
    except Exception:
        pass
    return False


async def _next_step(page) -> str | None:
    """Click Next / Continue / Save & Continue button. Returns label or None."""
    try:
        label = await page.evaluate("""() => {
            const kws = ['next', 'continue', 'save & continue', 'save and continue', 'next step'];
            const btns = Array.from(document.querySelectorAll('button, input[type="button"]'));
            for (const kw of kws) {
                for (const btn of btns) {
                    const t = (btn.innerText || btn.value || '').trim().toLowerCase();
                    if (t === kw || t.startsWith(kw)) {
                        if (!btn.disabled) { btn.click(); return t; }
                    }
                }
            }
            return null;
        }""")
        if label:
            await page.wait_for_timeout(2000)
        return label
    except Exception:
        return None


# ── Greenhouse ─────────────────────────────────────────────────────────────────

async def apply_greenhouse(page, url: str, job: dict) -> bool:
    print(f"  [Greenhouse] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click "Apply for this job" button if present
        try:
            await page.click("a#apply_button, a[href*='#app'], button:has-text('Apply'), a:has-text('Apply for this job')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        # Basic fields
        await _fill_any(page, ["#first_name", "input[name='first_name']", "input[placeholder*='First']"], INFO["first"])
        await _fill_any(page, ["#last_name",  "input[name='last_name']",  "input[placeholder*='Last']"],  INFO["last"])
        await _fill_any(page, ["#email",       "input[name='email']",      "input[type='email']"],         INFO["email"])
        await _fill_any(page, ["#phone",       "input[name='phone']",      "input[type='tel']"],           INFO["phone"])

        # LinkedIn / Website / GitHub
        await _fill_any(page, [
            "input#linkedin_profile", "input[name*='linkedin']",
            "input[placeholder*='LinkedIn']"
        ], INFO["linkedin"])
        await _fill_any(page, [
            "input#website", "input[name*='github']", "input[name*='website']",
            "input[placeholder*='GitHub']", "input[placeholder*='website']",
        ], INFO["github"])

        # Resume
        await _upload_resume(page)
        await page.wait_for_timeout(500)

        # Cover letter
        await _fill_cover_letter(page, job)

        # Location
        await _fill_any(page, [
            "input[name*='location']", "input[placeholder*='City']", "input[placeholder*='Location']"
        ], INFO["city"])

        # Answer yes/no questions
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        # Submit
        submitted = await _submit(page)
        if submitted:
            await page.wait_for_timeout(2000)
            # Check for success indicators
            success_text = await page.evaluate("""() => {
                const body = document.body.innerText.toLowerCase();
                return body.includes('thank you') || body.includes('application received') || body.includes('successfully submitted');
            }""")
            if success_text:
                print("  [Greenhouse] Application submitted!")
                return True
            print("  [Greenhouse] Submit clicked — may need verification")
            return True  # assume success if no error shown
        return False

    except Exception as e:
        print(f"  [Greenhouse] Error: {e}")
        return False


# ── Lever ──────────────────────────────────────────────────────────────────────

async def apply_lever(page, url: str, job: dict) -> bool:
    print(f"  [Lever] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click "Apply" button if on job description page
        try:
            await page.click("a.template-btn-submit, a:has-text('Apply for this job'), a:has-text('Apply now')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        # Full name (Lever uses a single name field)
        await _fill_any(page, [
            "input[name='name']", "#name",
            "input[placeholder*='Full name']", "input[placeholder*='Name']"
        ], INFO["name"])

        # Email
        await _fill_any(page, [
            "input[name='email']", "#email", "input[type='email']"
        ], INFO["email"])

        # Phone
        await _fill_any(page, [
            "input[name='phone']", "#phone", "input[type='tel']"
        ], INFO["phone"])

        # LinkedIn URL — Lever puts this as "urls[LinkedIn]" or similar
        await _fill_any(page, [
            "input[name='urls[LinkedIn]']", "input[name*='linkedin']",
            "input[placeholder*='LinkedIn']"
        ], INFO["linkedin"])

        # GitHub
        await _fill_any(page, [
            "input[name='urls[GitHub]']", "input[name*='github']",
            "input[placeholder*='GitHub']", "input[placeholder*='Portfolio']"
        ], INFO["github"])

        # Website / portfolio
        await _fill_any(page, [
            "input[name='urls[Portfolio]']", "input[name*='website']",
            "input[placeholder*='Website']", "input[placeholder*='portfolio']"
        ], INFO["website"])

        # Resume upload
        await _upload_resume(page)
        await page.wait_for_timeout(500)

        # Cover letter / additional info text area
        await _fill_cover_letter(page, job)

        # Location
        await _fill_any(page, [
            "input[name='location']", "input[placeholder*='Location']",
            "input[placeholder*='City']"
        ], INFO["city"])

        # Yes/No questions
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        # Submit
        submitted = await _submit(page)
        if submitted:
            await page.wait_for_timeout(2000)
            success = await page.evaluate("""() => {
                const b = document.body.innerText.toLowerCase();
                return b.includes('thank you') || b.includes('submitted') || b.includes('application received');
            }""")
            print(f"  [Lever] Submit clicked, success={success}")
            return True
        return False

    except Exception as e:
        print(f"  [Lever] Error: {e}")
        return False


# ── Workday ────────────────────────────────────────────────────────────────────

async def apply_workday(page, url: str, job: dict) -> bool:
    print(f"  [Workday] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Click the Apply button on the job listing page
        try:
            await page.click("a[data-uxi-element-id='applyButton'], button:has-text('Apply'), a:has-text('Apply')", timeout=5000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Workday often asks to create account or sign in — try "Apply Manually"
        try:
            await page.click("button:has-text('Apply Manually'), a:has-text('Apply Manually')", timeout=3000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        # Step through Workday's multi-step form (up to 10 steps)
        for step in range(10):
            await page.wait_for_timeout(1500)

            # Try uploading resume on every step (Workday shows upload on step 1)
            await _upload_resume(page)

            # Fill name fields
            await _fill_any(page, [
                "input[data-automation-id='legalNameSection_firstName']",
                "input[placeholder*='First Name']", "input[name*='firstName']"
            ], INFO["first"])
            await _fill_any(page, [
                "input[data-automation-id='legalNameSection_lastName']",
                "input[placeholder*='Last Name']", "input[name*='lastName']"
            ], INFO["last"])

            # Email
            await _fill_any(page, [
                "input[data-automation-id='email']", "input[type='email']",
                "input[placeholder*='Email']"
            ], INFO["email"])

            # Phone
            await _fill_any(page, [
                "input[data-automation-id='phone-number']",
                "input[type='tel']", "input[placeholder*='Phone']"
            ], INFO["phone"])

            # Country
            try:
                country_sel = await page.query_selector(
                    "select[data-automation-id='countryDropdown'], select[placeholder*='Country']"
                )
                if country_sel:
                    await country_sel.select_option(label="Ireland")
            except Exception:
                pass

            # City
            await _fill_any(page, [
                "input[data-automation-id='city']", "input[placeholder*='City']"
            ], INFO["city"])

            # Answer yes/no questions
            await _answer_yes_no(page)
            await page.wait_for_timeout(300)

            # Check if we can submit
            can_submit = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                return btns.some(b => {
                    const t = (b.innerText || '').trim().toLowerCase();
                    return t === 'submit' || t === 'submit application';
                });
            }""")
            if can_submit:
                submitted = await _submit(page)
                if submitted:
                    print(f"  [Workday] Application submitted (step {step})!")
                    return True

            # Move to next step
            nxt = await _next_step(page)
            if not nxt:
                # Try clicking Save & Continue
                try:
                    await page.click("button:has-text('Save & Continue'), button:has-text('Next')", timeout=3000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    break

        return False

    except Exception as e:
        print(f"  [Workday] Error: {e}")
        return False


# ── SmartRecruiters ────────────────────────────────────────────────────────────

async def apply_smartrecruiters(page, url: str, job: dict) -> bool:
    print(f"  [SmartRecruiters] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click Apply button
        try:
            await page.click("button:has-text('Apply'), a:has-text('Apply')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        # Step through
        for step in range(8):
            await page.wait_for_timeout(1200)
            await _upload_resume(page)
            await _fill_any(page, ["input[name='firstName']", "input[placeholder*='First']"], INFO["first"])
            await _fill_any(page, ["input[name='lastName']",  "input[placeholder*='Last']"],  INFO["last"])
            await _fill_any(page, ["input[name='email']",     "input[type='email']"],          INFO["email"])
            await _fill_any(page, ["input[name='phoneNumber']", "input[type='tel']"],           INFO["phone"])
            await _fill_any(page, ["input[name*='linkedin']",   "input[placeholder*='LinkedIn']"], INFO["linkedin"])
            await _answer_yes_no(page)
            await _fill_cover_letter(page, job)

            can_submit = await page.evaluate("""() => Array.from(document.querySelectorAll('button')).some(b => b.innerText.trim().toLowerCase() === 'send application')""")
            if can_submit:
                submitted = await _submit(page)
                if submitted:
                    print("  [SmartRecruiters] Application sent!")
                    return True
            nxt = await _next_step(page)
            if not nxt:
                break

        return False

    except Exception as e:
        print(f"  [SmartRecruiters] Error: {e}")
        return False


# ── Ashby ──────────────────────────────────────────────────────────────────────

async def apply_ashby(page, url: str, job: dict) -> bool:
    print(f"  [Ashby] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        try:
            await page.click("a:has-text('Apply'), button:has-text('Apply')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        await _fill_any(page, ["input[name='name']",  "input[placeholder*='Name']"],  INFO["name"])
        await _fill_any(page, ["input[name='email']", "input[type='email']"],          INFO["email"])
        await _fill_any(page, ["input[name='phone']", "input[type='tel']"],            INFO["phone"])
        await _fill_any(page, ["input[name*='linkedin']", "input[placeholder*='LinkedIn']"], INFO["linkedin"])

        await _upload_resume(page)
        await _fill_cover_letter(page, job)
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        submitted = await _submit(page)
        if submitted:
            print("  [Ashby] Application submitted!")
            return True
        return False

    except Exception as e:
        print(f"  [Ashby] Error: {e}")
        return False


# ── Workable ───────────────────────────────────────────────────────────────────

async def apply_workable(page, url: str, job: dict) -> bool:
    print(f"  [Workable] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        try:
            await page.click("button:has-text('Apply for this job'), a:has-text('Apply')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        await _fill_any(page, ["input[name='firstname']",  "input[name='firstName']",  "input[placeholder*='First']"], INFO["first"])
        await _fill_any(page, ["input[name='lastname']",   "input[name='lastName']",   "input[placeholder*='Last']"],  INFO["last"])
        await _fill_any(page, ["input[name='email']",      "input[type='email']"],                                    INFO["email"])
        await _fill_any(page, ["input[name='phone']",      "input[type='tel']"],                                      INFO["phone"])
        await _fill_any(page, ["input[name*='linkedin']",  "input[placeholder*='LinkedIn']"],                          INFO["linkedin"])

        await _upload_resume(page)
        await _fill_cover_letter(page, job)
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        submitted = await _submit(page)
        if submitted:
            print("  [Workable] Application submitted!")
            return True
        return False

    except Exception as e:
        print(f"  [Workable] Error: {e}")
        return False


# ── BambooHR ───────────────────────────────────────────────────────────────────

async def apply_bamboohr(page, url: str, job: dict) -> bool:
    print(f"  [BambooHR] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        try:
            await page.click("a:has-text('Apply'), button:has-text('Apply')", timeout=4000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        await _fill_any(page, ["#firstName",  "input[name='firstName']"],  INFO["first"])
        await _fill_any(page, ["#lastName",   "input[name='lastName']"],   INFO["last"])
        await _fill_any(page, ["#email",      "input[name='email']"],      INFO["email"])
        await _fill_any(page, ["#phone",      "input[name='phoneNumber']"], INFO["phone"])
        await _fill_any(page, ["input[name*='linkedin']", "input[placeholder*='LinkedIn']"], INFO["linkedin"])

        await _upload_resume(page)
        await _fill_cover_letter(page, job)
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        submitted = await _submit(page)
        if submitted:
            print("  [BambooHR] Application submitted!")
            return True
        return False

    except Exception as e:
        print(f"  [BambooHR] Error: {e}")
        return False


# ── Generic fallback ───────────────────────────────────────────────────────────

async def apply_generic(page, url: str, job: dict) -> bool:
    """Best-effort: fill visible text/email/tel inputs, upload resume, submit."""
    print(f"  [Generic] {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)

        # Try to click an Apply button first
        try:
            await page.click("a:has-text('Apply'), button:has-text('Apply')", timeout=3000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        # Fill all visible text inputs intelligently by their labels/placeholders
        await page.evaluate(f"""() => {{
            const fill = (el, val) => {{
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(el, val);
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }};

            const getLabel = el => {{
                const id = el.id;
                const lbl = id ? document.querySelector('label[for="'+id+'"]') : null;
                return (lbl?.innerText || el.placeholder || el.name || el.getAttribute('aria-label') || '').toLowerCase();
            }};

            document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input:not([type])').forEach(el => {{
                if (el.readOnly || el.disabled || el.value) return;
                const lbl = getLabel(el);
                if (lbl.includes('first')) fill(el, '{INFO["first"]}');
                else if (lbl.includes('last')) fill(el, '{INFO["last"]}');
                else if (lbl.includes('name') && !lbl.includes('user') && !lbl.includes('company')) fill(el, '{INFO["name"]}');
                else if (lbl.includes('email') || el.type === 'email') fill(el, '{INFO["email"]}');
                else if (lbl.includes('phone') || el.type === 'tel') fill(el, '{INFO["phone"]}');
                else if (lbl.includes('linkedin')) fill(el, '{INFO["linkedin"]}');
                else if (lbl.includes('github') || lbl.includes('portfolio') || lbl.includes('website')) fill(el, '{INFO["github"]}');
                else if (lbl.includes('city') || lbl.includes('location')) fill(el, '{INFO["city"]}');
                else if (lbl.includes('country')) fill(el, '{INFO["country"]}');
                else if (lbl.includes('zip') || lbl.includes('postal')) fill(el, '{INFO["zip"]}');
            }});
        }}""")
        await page.wait_for_timeout(500)

        await _upload_resume(page)
        await _fill_cover_letter(page, job)
        await _answer_yes_no(page)
        await page.wait_for_timeout(500)

        submitted = await _submit(page)
        if submitted:
            print("  [Generic] Application submitted!")
            return True

        # If no submit yet, maybe it's multi-step — try Next a few times
        for _ in range(5):
            nxt = await _next_step(page)
            if not nxt:
                break
            await _upload_resume(page)
            await _answer_yes_no(page)
            await page.wait_for_timeout(500)
            submitted = await _submit(page)
            if submitted:
                print("  [Generic] Application submitted (multi-step)!")
                return True

        return False

    except Exception as e:
        print(f"  [Generic] Error: {e}")
        return False


# ── Main dispatcher ────────────────────────────────────────────────────────────

async def apply_external(page, url: str, job: dict) -> bool:
    """Detect ATS type and run the matching handler."""
    ats = detect_ats(url)
    print(f"  [external_apply] ATS={ats} url={url[:80]}")

    handlers = {
        "greenhouse":     apply_greenhouse,
        "lever":          apply_lever,
        "workday":        apply_workday,
        "smartrecruiters": apply_smartrecruiters,
        "ashby":          apply_ashby,
        "workable":       apply_workable,
        "bamboohr":       apply_bamboohr,
    }
    handler = handlers.get(ats, apply_generic)
    return await handler(page, url, job)
