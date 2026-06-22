import sqlite3
conn = sqlite3.connect("applied_jobs.db")
rows = conn.execute("SELECT MIN(found_at), MAX(found_at), COUNT(*) FROM jobs").fetchone()
print(f"Oldest: {rows[0]}, Newest: {rows[1]}, Total: {rows[2]}")
rows2 = conn.execute("SELECT found_at, title, company FROM jobs ORDER BY found_at DESC LIMIT 5").fetchall()
print("Most recent jobs:")
for r in rows2:
    print(f"  {r[0]}  {r[1]} @ {r[2]}")
conn.close()
