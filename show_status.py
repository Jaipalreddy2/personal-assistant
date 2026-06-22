import sqlite3
conn = sqlite3.connect("applied_jobs.db")
print("Status counts:")
for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall():
    print(f"  {r[0]}: {r[1]}")
print("\nApplied jobs:")
for r in conn.execute("SELECT title, company FROM jobs WHERE status='applied' LIMIT 20").fetchall():
    print(f"  {r[0]} @ {r[1]}")
print("\nFailed jobs:")
for r in conn.execute("SELECT title, company FROM jobs WHERE status='failed' LIMIT 30").fetchall():
    print(f"  {r[0]} @ {r[1]}")
conn.close()
