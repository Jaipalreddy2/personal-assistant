import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "applied_jobs.db"
RETRY_IDS_FILE = Path(__file__).parent / "_retry_ids.txt"

ids = RETRY_IDS_FILE.read_text().strip().splitlines()
conn = sqlite3.connect(DB)

# Mark as skipped
conn.execute(f"UPDATE jobs SET status='skipped' WHERE id IN ({','.join('?'*len(ids))})", ids)
conn.commit()

# Show links
rows = conn.execute(
    f"SELECT title, company, url FROM jobs WHERE id IN ({','.join('?'*len(ids))})", ids
).fetchall()
conn.close()

print("These jobs require MANUAL application (no Easy Apply):\n")
for title, company, url in rows:
    print(f"  {title} @ {company}")
    print(f"  {url}\n")
print(f"Marked {len(rows)} jobs as skipped.")
