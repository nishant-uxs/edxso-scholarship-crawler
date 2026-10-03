"""Finalize demo artifacts: multi-source crawl, change detection, stale examples."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

from scholarship_intel.pipeline import run_crawl
from scholarship_intel.store import db as store

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "scholarships.db"
SAMPLE = ROOT / "data" / "scholarships.sample.db"


def export_samples(conn) -> None:
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id,name,provider,official_source_url,application_url,source_type,"
            "amount_benefit,eligibility,income_criteria,closing_date,lifecycle_status,"
            "confidence_score,verification_label,last_verified_at FROM scholarships "
            "ORDER BY confidence_score DESC"
        )
    ]
    (ROOT / "data" / "sample_scholarships.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    changes = [dict(r) for r in conn.execute("SELECT * FROM change_events ORDER BY id")]
    (ROOT / "data" / "sample_changes.json").write_text(
        json.dumps(changes, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    if DB.exists():
        DB.unlink()

    print("=== Full multi-source crawl ===")
    stats = run_crawl(db_path=DB, max_discover_pages=30)
    print(stats)

    print("\n=== Seed prior deadlines for change detection ===")
    conn = store.connect(DB)
    rows = conn.execute(
        "SELECT id, slug, closing_date FROM scholarships "
        "WHERE closing_date IS NOT NULL AND closing_date != 'Not specified' "
        "AND official_source_url LIKE '%All-Scholarships%' "
        "ORDER BY id LIMIT 3"
    ).fetchall()
    for row in rows[:2]:
        conn.execute(
            "UPDATE scholarships SET closing_date=? WHERE id=?",
            ("2026-08-31", row["id"]),
        )
        print("seeded old closing_date for", row["slug"][:55])
    conn.commit()
    conn.close()

    print("\n=== Re-crawl NSP listing (detect deadline changes + missing) ===")
    stats2 = run_crawl(db_path=DB, max_discover_pages=8, mark_missing=True)
    print("changed", stats2.get("changed"), "missing_marked", stats2.get("expired_marked"))

    print("\n=== Lifecycle reconcile from evidenced closing dates ===")
    conn = store.connect(DB)
    today = date.today()
    for row in conn.execute(
        "SELECT id, closing_date, lifecycle_status, name FROM scholarships "
        "WHERE closing_date != 'Not specified' AND closing_date IS NOT NULL"
    ).fetchall():
        try:
            d = date.fromisoformat(row["closing_date"])
        except ValueError:
            continue
        if d < today and row["lifecycle_status"] != "EXPIRED":
            conn.execute(
                "UPDATE scholarships SET lifecycle_status='EXPIRED' WHERE id=?",
                (row["id"],),
            )
            conn.execute(
                """INSERT INTO change_events
                   (scholarship_id, field, old_value, new_value, detected_at, source_url, evidence_snippet)
                   VALUES (?, 'lifecycle_status', ?, 'EXPIRED', ?, ?, ?)""",
                (
                    row["id"],
                    row["lifecycle_status"],
                    datetime.utcnow().isoformat(),
                    "lifecycle://closing_date_passed",
                    f"Closing date {row['closing_date']} < {today.isoformat()}",
                ),
            )
            print("EXPIRED", row["name"][:60])

    export_samples(conn)
    s = store.dashboard_stats(conn)
    print("\n=== Final stats ===")
    for k, v in s.items():
        print(f"  {k}: {v}")
    with_amount = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE amount_benefit != 'Not specified'"
    ).fetchone()["c"]
    with_income = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE income_criteria != 'Not specified'"
    ).fetchone()["c"]
    print(f"  with_amount: {with_amount}")
    print(f"  with_income: {with_income}")
    conn.close()

    shutil.copy(DB, SAMPLE)
    print("copied", SAMPLE)


if __name__ == "__main__":
    main()
