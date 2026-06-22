import sqlite3
conn = sqlite3.connect("applied_jobs.db")
print("=== Status counts ===")
for r in conn.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status").fetchall():
    print(f"  {r[0]}: {r[1]}")
print("\n=== Applied jobs ===")
for r in conn.execute("SELECT title,company FROM jobs WHERE status='applied'").fetchall():
    print(f"  ✅ {r[0]} @ {r[1]}")
print("\n=== Failed jobs ===")
for r in conn.execute("SELECT title,company FROM jobs WHERE status='failed'").fetchall():
    print(f"  ❌ {r[0]} @ {r[1]}")
conn.close()
