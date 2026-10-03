"""Discover -> Crawl -> Extract -> Verify -> Store -> Update."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from scholarship_intel.discovery.classify import classify_source_type, is_official_domain
from scholarship_intel.enrich import enrich_batch
from scholarship_intel.extract.documents import extract_from_document, pdf_to_text
from scholarship_intel.extract.parsers import (
    discover_links,
    extract_detail_page,
    extract_nsp_listing,
)
from scholarship_intel.fetch import Fetcher
from scholarship_intel.models import ScholarshipRecord, SourceType
from scholarship_intel.store import db as store
from scholarship_intel.verify.engine import enrich_lifecycle, score_scholarship

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEEDS = ROOT / "config" / "seeds.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_SEEDS
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_records(
    url: str,
    final_url: str,
    text: str,
    content_bytes: bytes | None,
    type_hint: str | None,
    role: str,
) -> list[ScholarshipRecord]:
    records: list[ScholarshipRecord] = []

    if final_url.lower().endswith(".pdf") or url.lower().endswith(".pdf"):
        pdf_text = text
        if content_bytes:
            try:
                pdf_text = pdf_to_text(content_bytes)
            except Exception as e:
                print(f"   PDF parse fail: {e}")
                return []
        st = classify_source_type(final_url, type_hint)
        rec = extract_from_document(pdf_text, final_url, st)
        return [rec] if rec else []

    if "scholarships.gov.in" in url and ("All-Scholarships" in url or role == "listing"):
        records = extract_nsp_listing(text, final_url)
        print(f"   NSP listing -> {len(records)} schemes")
        return records

    st = classify_source_type(final_url, type_hint)
    detail = extract_detail_page(text, final_url, st)
    if detail:
        records.append(detail)
        print(f"   Detail extract -> {detail.name[:60]}")

    # Press / FAQ-style HTML also goes through document extractor when detail is thin
    doc = extract_from_document(text, final_url, st)
    if doc:
        if not records:
            records.append(doc)
            print(f"   Document extract -> {doc.name[:60]}")
        else:
            # Merge richer doc fields into detail
            from scholarship_intel.enrich import merge_evidenced_fields

            n = merge_evidenced_fields(records[0], doc)
            if n:
                print(f"   Merged {n} evidenced fields from page text")
            # Prefer document closing date if detail lacked it
            if (
                records[0].closing_date.value in (None, "Not specified")
                and doc.closing_date.value not in (None, "Not specified")
            ):
                records[0].closing_date = doc.closing_date
                records[0].lifecycle_status = doc.lifecycle_status
    return records


def run_crawl(
    db_path: Path | str | None = None,
    seeds_path: Path | None = None,
    max_discover_pages: int = 25,
    mark_missing: bool = False,
) -> dict[str, Any]:
    cfg = load_config(seeds_path)
    official = cfg.get("official_domain_suffixes", [])
    aggregators = cfg.get("aggregator_domains", [])
    seeds = cfg.get("seeds", [])

    conn = store.connect(db_path)
    run_id = store.start_run(conn)
    fetcher = Fetcher()

    stats: dict[str, Any] = {
        "discovered": 0,
        "upserted": 0,
        "unchanged": 0,
        "changed": 0,
        "expired_marked": 0,
        "enriched_fields": 0,
        "errors": [],
    }
    seen_slugs: set[str] = set()
    listing_slugs: set[str] = set()
    queue: list[tuple[str, str | None, str, str | None]] = []
    batch: list[ScholarshipRecord] = []

    for s in seeds:
        queue.append(
            (
                s["url"],
                s.get("source_type"),
                s.get("discovery_role", "hub"),
                s.get("official_url"),
            )
        )

    visited: set[str] = set()
    pages_fetched = 0

    try:
        while queue and pages_fetched < max_discover_pages:
            url, type_hint, role, official_url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            print(f"-> Fetch {url}")
            fr = fetcher.get(url)
            pages_fetched += 1
            if not fr.ok:
                stats["errors"].append(f"{url}: {fr.error}")
                print(f"   FAIL {fr.error}")
                continue

            content_bytes = fr.content
            text = fr.text
            is_pdf = (
                url.lower().endswith(".pdf")
                or str(fr.final_url).lower().endswith(".pdf")
                or (content_bytes or b"").startswith(b"%PDF")
            )
            if is_pdf and content_bytes and content_bytes.startswith(b"%PDF"):
                text = ""
            elif is_pdf and content_bytes and not content_bytes.startswith(b"%PDF"):
                text = content_bytes.decode("utf-8", errors="ignore")
                content_bytes = None

            source_url = official_url or (
                fr.final_url if not url.startswith(("local:", "file:")) else url
            )
            records = _extract_records(url, source_url, text, content_bytes, type_hint, role)
            if "All-Scholarships" in (official_url or url):
                for rec in records:
                    listing_slugs.add(rec.slug)

            can_discover = role in ("hub", "listing") and text and not is_pdf
            if can_discover and is_official_domain(source_url if official_url else fr.final_url, official):
                links = discover_links(text, fr.final_url if not url.startswith(("local:", "file:")) else source_url, official)
                for link in links:
                    if link not in visited:
                        queue.append((link, type_hint, "detail", None))

            batch.extend(records)

        # Cross-enrich matching names (e.g. UGC detail amount -> NSP listing)
        stats["enriched_fields"] = enrich_batch(batch)
        if stats["enriched_fields"]:
            print(f"   Cross-enrichment filled {stats['enriched_fields']} fields")

        for rec in batch:
            rec.lifecycle_status = enrich_lifecycle(rec)
            rec.verification = score_scholarship(
                rec,
                official_suffixes=official,
                aggregator_domains=aggregators,
                page_fetch_ok=True,
            )
            rec.last_verified_at = datetime.utcnow()
            seen_slugs.add(rec.slug)
            stats["discovered"] += 1

            existing = store.get_by_slug(conn, rec.slug)
            _sid, changes = store.upsert_scholarship(conn, rec)
            if not existing:
                stats["upserted"] += 1
                print(
                    f"   + {rec.name[:55]}  "
                    f"conf={rec.verification.score}% {rec.verification.label.value}"
                )
            elif changes:
                stats["changed"] += 1
                stats["upserted"] += 1
                print(f"   ~ {rec.name[:55]}  {len(changes)} change(s)")
            else:
                stats["unchanged"] += 1

        if mark_missing and listing_slugs:
            # Only mark prior NSP-listing rows missing from this listing re-crawl
            stats["expired_marked"] = store.mark_missing_listing(
                conn, listing_slugs, source_url_substr="All-Scholarships"
            )

    finally:
        fetcher.close()
        store.finish_run(conn, run_id, stats)
        conn.close()

    stats["run_id"] = run_id
    stats["pages_fetched"] = pages_fetched
    stats["unique_seen"] = len(seen_slugs)
    return stats
