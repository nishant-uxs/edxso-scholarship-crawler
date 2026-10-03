import json
from scholarship_intel.store import db as store

conn = store.connect("data/scholarships.db")
row = conn.execute(
    "SELECT name, eligibility, evidence_json, confidence_json, lifecycle_status "
    "FROM scholarships WHERE name LIKE '%Pragati%' LIMIT 1"
).fetchone()
print("NAME", row["name"])
print("ELIG", row["eligibility"])
print("STATUS", row["lifecycle_status"])
ev = json.loads(row["evidence_json"] or "{}")
print("EV KEYS", list(ev.keys()))
conf = json.loads(row["confidence_json"] or "{}")
print("FACTORS", conf.get("factors"))
for r in conf.get("reasons", []):
    print("-", r)
