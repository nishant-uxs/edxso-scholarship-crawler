"""SQLite persistence with change history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from scholarship_intel.models import (
    ChangeEvent,
    ConfidenceBreakdown,
    FieldValue,
    LifecycleStatus,
    ScholarshipRecord,
    SourceType,
    VerificationLabel,
)

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "scholarships.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  discovered INTEGER DEFAULT 0,
  upserted INTEGER DEFAULT 0,
  unchanged INTEGER DEFAULT 0,
  changed INTEGER DEFAULT 0,
  expired_marked INTEGER DEFAULT 0,
  errors_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS scholarships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  official_source_url TEXT NOT NULL,
  application_url TEXT,
  source_type TEXT NOT NULL,
  discovery_url TEXT,
  amount_benefit TEXT,
  eligibility TEXT,
  academic_requirements TEXT,
  education_level TEXT,
  income_criteria TEXT,
  age_criteria TEXT,
  gender_criteria TEXT,
  category_criteria TEXT,
  domicile_state TEXT,
  institution_requirements TEXT,
  opening_date TEXT,
  closing_date TEXT,
  documents_required TEXT,
  selection_process TEXT,
  renewal_requirements TEXT,
  lifecycle_status TEXT NOT NULL,
  confidence_score REAL,
  verification_label TEXT,
  confidence_json TEXT,
  evidence_json TEXT,
  last_verified_at TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  content_hash TEXT,
  raw_excerpt TEXT,
  extra_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS change_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scholarship_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  detected_at TEXT NOT NULL,
  source_url TEXT NOT NULL,
  evidence_snippet TEXT,
  FOREIGN KEY (scholarship_id) REFERENCES scholarships(id)
);

CREATE INDEX IF NOT EXISTS idx_scholarships_status ON scholarships(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_scholarships_label ON scholarships(verification_label);
CREATE INDEX IF NOT EXISTS idx_changes_scholarship ON change_events(scholarship_id);
"""

TRACKED_FIELDS = [
    "name",
    "provider",
    "official_source_url",
    "application_url",
    "amount_benefit",
    "eligibility",
    "academic_requirements",
    "education_level",
    "income_criteria",
    "age_criteria",
    "gender_criteria",
    "category_criteria",
    "domicile_state",
    "institution_requirements",
    "opening_date",
    "closing_date",
    "documents_required",
    "selection_process",
    "renewal_requirements",
    "lifecycle_status",
]


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _fv(v: FieldValue | str | None) -> str:
    if isinstance(v, FieldValue):
        return v.value or "Not specified"
    return v or "Not specified"


def _evidence_bundle(rec: ScholarshipRecord) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in TRACKED_FIELDS:
        attr = getattr(rec, name, None)
        if isinstance(attr, FieldValue) and attr.evidence:
            out[name] = attr.evidence.model_dump(mode="json")
    return out


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (started_at) VALUES (?)",
        (datetime.utcnow().isoformat(),),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, stats: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE crawl_runs SET finished_at=?, discovered=?, upserted=?, unchanged=?,
           changed=?, expired_marked=?, errors_json=? WHERE id=?""",
        (
            datetime.utcnow().isoformat(),
            stats.get("discovered", 0),
            stats.get("upserted", 0),
            stats.get("unchanged", 0),
            stats.get("changed", 0),
            stats.get("expired_marked", 0),
            json.dumps(stats.get("errors", [])),
            run_id,
        ),
    )
    conn.commit()


def get_by_slug(conn: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM scholarships WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


def upsert_scholarship(
    conn: sqlite3.Connection,
    rec: ScholarshipRecord,
) -> tuple[int, list[ChangeEvent]]:
    """Insert or update; return (id, change_events)."""
    now = datetime.utcnow().isoformat()
    existing = get_by_slug(conn, rec.slug)
    changes: list[ChangeEvent] = []
    conf = rec.verification
    evidence = _evidence_bundle(rec)

    values = {
        "slug": rec.slug,
        "name": rec.name,
        "provider": rec.provider,
        "official_source_url": rec.official_source_url,
        "application_url": rec.application_url,
        "source_type": rec.source_type.value,
        "discovery_url": rec.discovery_url,
        "amount_benefit": _fv(rec.amount_benefit),
        "eligibility": _fv(rec.eligibility),
        "academic_requirements": _fv(rec.academic_requirements),
        "education_level": _fv(rec.education_level),
        "income_criteria": _fv(rec.income_criteria),
        "age_criteria": _fv(rec.age_criteria),
        "gender_criteria": _fv(rec.gender_criteria),
        "category_criteria": _fv(rec.category_criteria),
        "domicile_state": _fv(rec.domicile_state),
        "institution_requirements": _fv(rec.institution_requirements),
        "opening_date": _fv(rec.opening_date),
        "closing_date": _fv(rec.closing_date),
        "documents_required": _fv(rec.documents_required),
        "selection_process": _fv(rec.selection_process),
        "renewal_requirements": _fv(rec.renewal_requirements),
        "lifecycle_status": rec.lifecycle_status.value,
        "confidence_score": conf.score if conf else None,
        "verification_label": conf.label.value if conf else None,
        "confidence_json": json.dumps(conf.model_dump(mode="json")) if conf else None,
        "evidence_json": json.dumps(evidence),
        "last_verified_at": (rec.last_verified_at or datetime.utcnow()).isoformat(),
        "last_seen_at": now,
        "content_hash": rec.content_hash,
        "raw_excerpt": (rec.raw_excerpt or "")[:4000],
        "extra_json": json.dumps(rec.extra),
    }

    if not existing:
        values["first_seen_at"] = now
        cols = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        cur = conn.execute(
            f"INSERT INTO scholarships ({cols}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        conn.commit()
        return int(cur.lastrowid), changes

    sid = int(existing["id"])
    for field in TRACKED_FIELDS:
        old = existing.get(field)
        new = values.get(field)
        if old is None:
            old = ""
        if new is None:
            new = ""
        if str(old).strip() != str(new).strip():
            snippet = None
            ev = evidence.get(field)
            if ev:
                snippet = ev.get("snippet")
            ch = ChangeEvent(
                scholarship_id=str(sid),
                field=field,
                old_value=str(old),
                new_value=str(new),
                detected_at=datetime.utcnow(),
                source_url=rec.official_source_url,
                evidence_snippet=snippet,
            )
            changes.append(ch)
            conn.execute(
                """INSERT INTO change_events
                   (scholarship_id, field, old_value, new_value, detected_at, source_url, evidence_snippet)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    field,
                    str(old),
                    str(new),
                    ch.detected_at.isoformat(),
                    rec.official_source_url,
                    snippet,
                ),
            )

    set_clause = ", ".join(f"{k}=?" for k in values if k != "slug")
    params = [v for k, v in values.items() if k != "slug"] + [sid]
    conn.execute(f"UPDATE scholarships SET {set_clause} WHERE id=?", params)
    conn.commit()
    return sid, changes


def mark_missing_as_unverifiable(conn: sqlite3.Connection, seen_slugs: set[str]) -> int:
    """Scholarships not seen in this crawl -> NO_LONGER_VERIFIABLE if previously active."""
    rows = conn.execute(
        "SELECT id, slug, lifecycle_status FROM scholarships WHERE lifecycle_status IN ('ACTIVE','EXPIRING_SOON')"
    ).fetchall()
    n = 0
    now = datetime.utcnow().isoformat()
    for row in rows:
        if row["slug"] not in seen_slugs:
            old = row["lifecycle_status"]
            conn.execute(
                "UPDATE scholarships SET lifecycle_status=?, last_seen_at=? WHERE id=?",
                (LifecycleStatus.NO_LONGER_VERIFIABLE.value, now, row["id"]),
            )
            conn.execute(
                """INSERT INTO change_events
                   (scholarship_id, field, old_value, new_value, detected_at, source_url, evidence_snippet)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    "lifecycle_status",
                    old,
                    LifecycleStatus.NO_LONGER_VERIFIABLE.value,
                    now,
                    "crawl://missing-from-source",
                    "Scholarship not found on official source during re-crawl",
                ),
            )
            n += 1
    conn.commit()
    return n


def mark_missing_listing(
    conn: sqlite3.Connection,
    seen_slugs: set[str],
    source_url_substr: str,
) -> int:
    """Mark listing-sourced rows missing from a re-crawl of the same listing."""
    rows = conn.execute(
        "SELECT id, slug, lifecycle_status, official_source_url FROM scholarships "
        "WHERE official_source_url LIKE ? AND lifecycle_status IN ('ACTIVE','EXPIRING_SOON','EXPIRED')",
        (f"%{source_url_substr}%",),
    ).fetchall()
    n = 0
    now = datetime.utcnow().isoformat()
    for row in rows:
        if row["slug"] in seen_slugs:
            continue
        old = row["lifecycle_status"]
        conn.execute(
            "UPDATE scholarships SET lifecycle_status=?, last_seen_at=? WHERE id=?",
            (LifecycleStatus.NO_LONGER_VERIFIABLE.value, now, row["id"]),
        )
        conn.execute(
            """INSERT INTO change_events
               (scholarship_id, field, old_value, new_value, detected_at, source_url, evidence_snippet)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                "lifecycle_status",
                old,
                LifecycleStatus.NO_LONGER_VERIFIABLE.value,
                now,
                row["official_source_url"],
                f"No longer present on listing page containing '{source_url_substr}'",
            ),
        )
        n += 1
    conn.commit()
    return n


def list_scholarships(
    conn: sqlite3.Connection,
    q: str | None = None,
    status: str | None = None,
    label: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM scholarships WHERE 1=1"
    params: list[Any] = []
    if q:
        sql += " AND (name LIKE ? OR provider LIKE ? OR eligibility LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    if status:
        sql += " AND lifecycle_status=?"
        params.append(status)
    if label:
        sql += " AND verification_label=?"
        params.append(label)
    sql += (
        " ORDER BY CASE WHEN confidence_score IS NULL THEN 1 ELSE 0 END, "
        "confidence_score DESC, name ASC LIMIT ?"
    )
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_scholarship(conn: sqlite3.Connection, sid: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM scholarships WHERE id=?", (sid,)).fetchone()
    return dict(row) if row else None


def get_changes(conn: sqlite3.Connection, sid: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM change_events WHERE scholarship_id=? ORDER BY detected_at DESC",
        (sid,),
    ).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) c FROM scholarships").fetchone()["c"]
    verified = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE verification_label='VERIFIED'"
    ).fetchone()["c"]
    review = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE verification_label='REVIEW_REQUIRED'"
    ).fetchone()["c"]
    active = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='ACTIVE'"
    ).fetchone()["c"]
    expired = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='EXPIRED'"
    ).fetchone()["c"]
    expiring = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE lifecycle_status='EXPIRING_SOON'"
    ).fetchone()["c"]
    avg_conf = conn.execute(
        "SELECT AVG(confidence_score) a FROM scholarships WHERE confidence_score IS NOT NULL"
    ).fetchone()["a"]
    recent = conn.execute(
        "SELECT COUNT(*) c FROM scholarships WHERE last_verified_at >= datetime('now', '-2 days')"
    ).fetchone()["c"]
    changes = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]
    source_types = conn.execute(
        "SELECT source_type, COUNT(*) c FROM scholarships GROUP BY source_type"
    ).fetchall()
    return {
        "total": total,
        "verified": verified,
        "review_required": review,
        "active": active,
        "expired": expired,
        "expiring_soon": expiring,
        "avg_confidence": round(avg_conf or 0, 1),
        "recently_updated": recent,
        "change_events": changes,
        "source_types": {r["source_type"]: r["c"] for r in source_types},
    }
