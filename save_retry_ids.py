import sqlite3
from pathlib import Path
DB = Path(__file__).parent / "applied_jobs.db"
conn = sqlite3.connect(DB)
# The 12 failed jobs — hardcoded from show_status output
failed_companies = [
    ('DevOps Engineer', 'Fruition Group Ireland'),
    ('DevOps Engineer', 'Ingenio Global'),
    ('DevOps Engineer', 'RECRUITERS'),
    ('DevOps Engineer', 'SearchWorks'),
    ('DevOps Engineer', 'Realtime Recruitment'),
    ('DevOps Engineer', 'GemPool Recruitment'),
    ('MSc/Phd Data Scientists & Engineers (RAIMS® Program)', 'Orcawise'),
    ('IT Support Engineer - Level 2', 'PFH Technology Group'),
    ('Data Cable Technician', 'DCS Recruitment'),
    ('IT Engineer', 'GoSafe'),
    ('IT Technical Support', 'Tusa IT Limited'),
    ('Data Centre Technician', 'CBRE'),
]
ids = []
for title, company in failed_companies:
    row = conn.execute(
        "SELECT id FROM jobs WHERE title=? AND company=? LIMIT 1", (title, company)
    ).fetchone()
    if row:
        ids.append(row[0])
        print(f"  Found: {title} @ {company}")
    else:
        print(f"  NOT FOUND: {title} @ {company}")
conn.close()
(Path(__file__).parent / "_retry_ids.txt").write_text("\n".join(ids))
print(f"\nSaved {len(ids)} job IDs to retry")
