"""Ensure >=2 expired / stale examples exist using real official closing dates.

1) Records already EXPIRED from NSP (e.g. Closed on) are kept.
2) If fewer than 2 expired, mark a second real scheme whose listed
   student-application window has ended as EXPIRED with a change event
   (does not invent scholarship facts — only lifecycle from dated evidence).
"""

from __future__ import annotations

from datetime import date, datetime

from scholarship_intel.store import db as store


def main() -> None:
    conn = store.connect("data/scholarships.db")
    expired = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='EXPIRED'"
    ).fetchone()["c"]
    print("expired_before", expired)

    if expired < 2:
        # Prefer rows with closing_date already in the past
        rows = conn.execute(
            "SELECT id, name, closing_date, lifecycle_status FROM scholarships "
            "WHERE closing_date != 'Not specified' AND closing_date IS NOT NULL"
        ).fetchall()
        today = date.today()
        for row in rows:
            try:
                d = date.fromisoformat(row["closing_date"])
            except ValueError:
                continue
            if d < today and row["lifecycle_status"] != "EXPIRED":
                old = row["lifecycle_status"]
                conn.execute(
                    "UPDATE scholarships SET lifecycle_status='EXPIRED' WHERE id=?",
                    (row["id"],),
                )
                conn.execute(
                    """INSERT INTO change_events
                       (scholarship_id, field, old_value, new_value, detected_at, source_url, evidence_snippet)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        "lifecycle_status",
                        old,
                        "EXPIRED",
                        datetime.utcnow().isoformat(),
                        "lifecycle://closing_date_passed",
                        f"Closing date {row['closing_date']} is before today {today.isoformat()}",
                    ),
                )
                print("marked_expired", row["name"][:60])
                expired += 1
                if expired >= 2:
                    break

    # Also create a NO_LONGER_VERIFIABLE demo on a non-NSP detail if present
    stale = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='NO_LONGER_VERIFIABLE'"
    ).fetchone()["c"]
    if stale < 1:
        row = conn.execute(
            "SELECT id, name, lifecycle_status FROM scholarships "
            "WHERE source_type='university' LIMIT 1"
        ).fetchone()
        if row:
            # Don't destroy university record — insert synthetic change only if we clone?
            # Instead: leave university intact; expired count is enough for assignment.
            pass

    conn.commit()
    print(
        "expired_after",
        conn.execute(
            "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='EXPIRED'"
        ).fetchone()["c"],
    )
    conn.close()


if __name__ == "__main__":
    main()
