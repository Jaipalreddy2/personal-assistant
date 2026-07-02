import sqlite3
conn = sqlite3.connect('applied_jobs.db')
rows = conn.execute(
    "SELECT id, title, company, status, found_at FROM jobs WHERE source='linkedin' ORDER BY found_at DESC LIMIT 10"
).fetchall()
for r in rows:
    print(r)
conn.close()
