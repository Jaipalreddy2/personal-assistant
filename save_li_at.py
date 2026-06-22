#!/usr/bin/env python3
"""
Usage:
  python save_li_at.py <li_at_value>
  python save_li_at.py <li_at_value> <JSESSIONID_value>

Get both values from Chrome: F12 -> Application -> Cookies -> linkedin.com
"""
import sys, json
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python save_li_at.py <li_at_value> [JSESSIONID_value]")
    sys.exit(1)

li_at     = sys.argv[1].strip().strip('"').strip("'")
jsession  = sys.argv[2].strip().strip('"').strip("'") if len(sys.argv) > 2 else ""

SESSION = Path(__file__).parent / "linkedin_session.json"

jsession_val = jsession if jsession else ""

cookies = [
    {"name": "li_at",      "value": li_at,        "domain": ".linkedin.com",     "path": "/", "expires": -1, "httpOnly": True,  "secure": True, "sameSite": "None"},
    {"name": "liap",       "value": "true",        "domain": ".linkedin.com",     "path": "/", "expires": -1, "httpOnly": False, "secure": True, "sameSite": "None"},
    {"name": "JSESSIONID", "value": jsession_val,  "domain": ".www.linkedin.com", "path": "/", "expires": -1, "httpOnly": True,  "secure": True, "sameSite": "None"},
]

SESSION.write_text(json.dumps({"cookies": cookies}))
print(f"Saved {len(cookies)} cookies to {SESSION.name}")
print("Run: python linkedin_apply.py apply")
