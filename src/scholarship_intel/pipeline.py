"""Discover -> Crawl -> Extract -> Verify -> Store -> Update."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from scholarship_intel.discovery.classify import classify_source_type, is_official_domain
from scholarship_intel.extract.parsers import (
    discover_links,
    extract_detail_page,
    extract_nsp_listing,
)
from scholarship_intel.fetch import Fetcher
from scholarship_intel.models import ScholarshipRecord
from scholarship_intel.store import db as store
from scholarship_intel.verify.engine import enrich_lifecycle, score_scholarship

console = Console(force_terminal=False, no_color=True)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEEDS = ROOT / "config" / "seeds.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_SEEDS
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


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
        "errors": [],
    }
    seen_slugs: set[str] = set()
    queue: list[tuple[str, str | None, str]] = []

    for s in seeds:
        queue.append((s["url"], s.get("source_type"), s.get("discovery_role", "hub")))

    visited: set[str] = set()
    pages_fetched = 0

    try:
        while queue and pages_fetched < max_discover_pages:
            url, type_hint, role = queue.pop(0)
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

            records: list[ScholarshipRecord] = []

            if "scholarships.gov.in" in url and ("All-Scholarships" in url or role == "listing"):
                records = extract_nsp_listing(fr.text, fr.final_url)
                print(f"   NSP listing -> {len(records)} schemes")
            else:
                st = classify_source_type(fr.final_url, type_hint)
                detail = extract_detail_page(fr.text, fr.final_url, st)
                if detail:
                    records = [detail]
                    print(f"   Detail extract -> {detail.name[:60]}")

            if role in ("hub", "listing") and is_official_domain(fr.final_url, official):
                links = discover_links(fr.text, fr.final_url, official)
                for link in links:
                    if link not in visited:
                        queue.append((link, type_hint, "detail"))

            for rec in records:
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

        if mark_missing:
            stats["expired_marked"] = store.mark_missing_as_unverifiable(conn, seen_slugs)

    finally:
        fetcher.close()
        store.finish_run(conn, run_id, stats)
        conn.close()

    stats["run_id"] = run_id
    stats["pages_fetched"] = pages_fetched
    stats["unique_seen"] = len(seen_slugs)
    return stats
