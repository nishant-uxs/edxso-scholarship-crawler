"""Build a static demo page summarizing the sample crawl (like Assignment 1)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "scholarships.sample.db"
OUT = ROOT / "docs" / "demo" / "index.html"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) c FROM scholarships").fetchone()["c"]
    verified = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE verification_label='VERIFIED'"
    ).fetchone()["c"]
    review = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE verification_label='REVIEW_REQUIRED'"
    ).fetchone()["c"]
    expired = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='EXPIRED'"
    ).fetchone()["c"]
    stale = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='NO_LONGER_VERIFIABLE'"
    ).fetchone()["c"]
    changes = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]
    avg = conn.execute(
        "SELECT AVG(confidence_score) a FROM scholarships WHERE confidence_score IS NOT NULL"
    ).fetchone()["a"]
    types = {
        r["source_type"]: r["c"]
        for r in conn.execute(
            "SELECT source_type, COUNT(*) c FROM scholarships GROUP BY source_type"
        )
    }
    top = conn.execute(
        "SELECT name, provider, confidence_score, verification_label, lifecycle_status, closing_date "
        "FROM scholarships ORDER BY confidence_score DESC LIMIT 12"
    ).fetchall()
    ch = conn.execute(
        "SELECT field, old_value, new_value, detected_at FROM change_events ORDER BY id LIMIT 8"
    ).fetchall()
    conn.close()

    rows = "".join(
        f"<tr><td>{r['name'][:70]}</td><td>{r['provider'][:40]}</td>"
        f"<td>{r['confidence_score']:.1f}%</td><td>{r['verification_label']}</td>"
        f"<td>{r['lifecycle_status']}</td><td>{r['closing_date']}</td></tr>"
        for r in top
    )
    ch_rows = "".join(
        f"<tr><td>{c['field']}</td><td>{c['old_value']}</td><td>{c['new_value']}</td>"
        f"<td>{c['detected_at']}</td></tr>"
        for c in ch
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scholarship Intelligence — Demo</title>
  <style>
    body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 0; background: #f3efe6; color: #1a1f16; }}
    header {{ padding: 2rem; background: #fffdf8; border-bottom: 1px solid #d5d0c4; }}
    h1 {{ margin: 0 0 .5rem; font-family: Georgia, serif; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(140px,1fr)); gap: .75rem; }}
    .m {{ background: #fffdf8; border: 1px solid #d5d0c4; border-radius: 10px; padding: .9rem; }}
    .m b {{ display:block; font-size: 1.5rem; color: #0f6b4c; }}
    table {{ width: 100%; border-collapse: collapse; background: #fffdf8; margin: 1rem 0 2rem; }}
    th, td {{ border-bottom: 1px solid #d5d0c4; padding: .55rem .7rem; text-align: left; font-size: .9rem; }}
    th {{ background: #f0ebe0; }}
    code {{ background: #e8e4da; padding: .1rem .35rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>Scholarship Intelligence — Working Demo</h1>
    <p>Edxso Assignment 2 · sample crawl from official sources (NSP / UGC / IIT Kanpur)</p>
  </header>
  <main>
    <section class="metrics">
      <div class="m"><b>{total}</b>Total discovered</div>
      <div class="m"><b>{verified}</b>Verified (≥95%)</div>
      <div class="m"><b>{review}</b>Review required</div>
      <div class="m"><b>{expired}</b>Expired</div>
      <div class="m"><b>{stale}</b>No longer verifiable</div>
      <div class="m"><b>{changes}</b>Change events</div>
      <div class="m"><b>{avg:.1f}%</b>Avg confidence</div>
    </section>
    <p>Source types: <code>{json.dumps(types)}</code></p>
    <h2>Top scholarships (sample)</h2>
    <table>
      <thead><tr><th>Name</th><th>Provider</th><th>Confidence</th><th>Label</th><th>Status</th><th>Deadline</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <h2>Change detection samples</h2>
    <table>
      <thead><tr><th>Field</th><th>Old</th><th>New</th><th>Detected</th></tr></thead>
      <tbody>{ch_rows}</tbody>
    </table>
    <p>Live dashboard: <code>python -m scholarship_intel.cli serve</code> → http://127.0.0.1:8765</p>
  </main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
