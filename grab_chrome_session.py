#!/usr/bin/env python3
"""
Extract LinkedIn li_at cookie from Chrome/Edge or via manual paste.
"""
import sys, io, json, shutil, os, sqlite3, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path

SESSION = Path(__file__).parent / "linkedin_session.json"


def try_browser_cookie3(browser="chrome"):
    try:
        import browser_cookie3
        fn = getattr(browser_cookie3, browser)
        cj = fn(domain_name=".linkedin.com")
        cookies = []
        for c in cj:
            cookies.append({
                "name":     c.name,
                "value":    c.value,
                "domain":   ("." + c.domain) if not c.domain.startswith(".") else c.domain,
                "path":     c.path or "/",
                "expires":  c.expires or -1,
                "httpOnly": False,
                "secure":   c.secure,
                "sameSite": "None",
            })
        return cookies
    except Exception as e:
        print(f"  {browser} error: {e}")
        return []


def build_session_from_li_at(li_at_value: str) -> list:
    """Build minimal cookie list from just the li_at value."""
    return [
        {"name": "li_at",      "value": li_at_value, "domain": ".linkedin.com", "path": "/", "expires": -1, "httpOnly": True,  "secure": True, "sameSite": "None"},
        {"name": "liap",       "value": "true",       "domain": ".linkedin.com", "path": "/", "expires": -1, "httpOnly": False, "secure": True, "sameSite": "None"},
        {"name": "JSESSIONID", "value": "",            "domain": ".www.linkedin.com", "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "None"},
    ]


def main():
    print("=== LinkedIn Session Grabber ===\n")

    # 1. Try browser_cookie3 with Chrome
    print("Trying Chrome cookies...")
    cookies = try_browser_cookie3("chrome")
    if not cookies:
        print("Trying Edge cookies...")
        cookies = try_browser_cookie3("edge")

    li_at = next((c for c in cookies if c["name"] == "li_at"), None) if cookies else None

    if li_at:
        print(f"Found li_at in browser cookies!")
    else:
        print("\nCould not read cookies automatically (browser may be locked).")
        print("\n--- MANUAL METHOD ---")
        print("1. Open Chrome/Edge and go to linkedin.com")
        print("2. Press F12 -> Application tab -> Cookies -> https://www.linkedin.com")
        print("3. Find 'li_at' and copy its Value")
        print("4. Paste it below and press Enter:\n")
        li_at_val = input("li_at value: ").strip()
        if not li_at_val:
            print("No value entered. Exiting.")
            sys.exit(1)
        cookies = build_session_from_li_at(li_at_val)
        li_at = cookies[0]

    # Fix domain
    for c in cookies:
        if c.get("domain", "").startswith(".www."):
            c["domain"] = c["domain"].replace(".www.", ".")

    SESSION.write_text(json.dumps({"cookies": cookies}))
    print(f"\nSaved {len(cookies)} cookies to {SESSION.name}")
    print("Run: python linkedin_apply.py apply")


if __name__ == "__main__":
    main()
