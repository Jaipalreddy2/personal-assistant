import json
from pathlib import Path
data = json.loads(Path("linkedin_session.json").read_text())
cookies = data.get("cookies", data) if isinstance(data, dict) else data
print(f"Cookie count: {len(cookies)}")
for c in cookies:
    print(f"  {c['name']}: domain={c['domain']} value_len={len(str(c['value']))}")
