import sqlite3
conn = sqlite3.connect("applied_jobs.db")
conn.execute("UPDATE jobs SET url = REPLACE(url, 'ie.linkedin.com', 'www.linkedin.com')")
conn.execute("UPDATE jobs SET status = 'approved' WHERE status = 'failed'")
conn.commit()
n = conn.execute("SELECT COUNT(*) FROM jobs WHERE url LIKE '%www.linkedin.com%'").fetchone()[0]
f = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='approved'").fetchone()[0]
print(f"Fixed {n} URLs to www.linkedin.com | {f} jobs now approved")
conn.close()
