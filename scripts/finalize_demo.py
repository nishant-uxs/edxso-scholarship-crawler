"""Finalize demo artifacts: change detection + stale examples."""

from __future__ import annotations

from datetime import date, datetime

from scholarship_intel.pipeline import run_crawl
from scholarship_intel.store import db as store


def main() -> None:
    db = "data/scholarships.db"

    print("=== Full crawl (multi-source) ===")
    stats = run_crawl(db_path=db, max_discover_pages=22)
    print(stats)

    print("\n=== Seed old deadlines for change detection ===")
    conn = store.connect(db)
    rows = conn.execute(
        "SELECT id, slug, closing_date FROM scholarships "
        "WHERE closing_date IS NOT NULL AND closing_date != 'Not specified' "
        "ORDER BY id LIMIT 3"
    ).fetchall()
    for row in rows[:2]:
        conn.execute(
            "UPDATE scholarships SET closing_date=? WHERE id=?",
            ("2026-08-31", row["id"]),
        )
        print("seeded old closing_date for", row["slug"][:50])
    conn.commit()
    conn.close()

    print("\n=== Re-crawl to detect changes ===")
    stats2 = run_crawl(db_path=db, max_discover_pages=12)
    print("changed", stats2.get("changed"))

    print("\n=== Stale / expired pass ===")
    conn = store.connect(db)
    # Ensure lifecycle reflects past closing dates
    today = date.today()
    for row in conn.execute(
        "SELECT id, closing_date, lifecycle_status, name FROM scholarships "
        "WHERE closing_date != 'Not specified'"
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
            print("EXPIRED", row["name"][:55])

    # Second stale example: mark a non-listing detail as unable to re-verify
    # if we only re-saw NSP listing slugs (simulates source removed / not reconfirmed).
    nsp_slugs = {
        r["slug"]
        for r in conn.execute(
            "SELECT slug FROM scholarships WHERE official_source_url LIKE '%All-Scholarships%'"
        ).fetchall()
    }
    marked = store.mark_missing_as_unverifiable(conn, nsp_slugs)
    print("NO_LONGER_VERIFIABLE marked", marked)
    conn.commit()

    s = store.dashboard_stats(conn)
    print("\n=== Final stats ===")
    for k, v in s.items():
        print(f"  {k}: {v}")
    changes = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]
    print("  change_events:", changes)
    conn.close()


if __name__ == "__main__":
    main()
