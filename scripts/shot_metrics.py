import sqlite3

conn = sqlite3.connect("data/scholarships.sample.db")
print("expired", conn.execute("select count(*) from scholarships where lifecycle_status='EXPIRED'").fetchone()[0])
print("nlv", conn.execute("select count(*) from scholarships where lifecycle_status='NO_LONGER_VERIFIABLE'").fetchone()[0])
print("changes", conn.execute("select count(*) from change_events").fetchone()[0])
print("verified_ge95", conn.execute("select count(*) from scholarships where confidence_score>=95").fetchone()[0])
for r in conn.execute(
    "select name, confidence_score from scholarships where verification_label='VERIFIED' limit 3"
):
    print(r)
