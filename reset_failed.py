import sqlite3
conn = sqlite3.connect("applied_jobs.db")
conn.execute("UPDATE jobs SET status='approved' WHERE status='failed'")
conn.commit()
rows = conn.execute("SELECT changes()").fetchone()[0]
print(f"Reset {rows} failed jobs to approved")
conn.close()
