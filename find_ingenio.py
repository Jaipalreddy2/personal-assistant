import sqlite3
conn = sqlite3.connect('applied_jobs.db')
rows = conn.execute("SELECT id, title, company FROM jobs WHERE company LIKE '%ngenio%'").fetchall()
for r in rows:
    print(r)
conn.close()
