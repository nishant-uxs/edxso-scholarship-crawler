"""Cross-source enrichment — copy evidenced fields between matching records only."""

from __future__ import annotations

import re

from scholarship_intel.models import FieldValue, ScholarshipRecord


def _norm(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\((?:merit|welfare) based scheme\)", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def merge_evidenced_fields(base: ScholarshipRecord, donor: ScholarshipRecord) -> int:
    """Fill Not specified fields on base from donor when donor has evidence. Returns count filled."""
    filled = 0
    fields = [
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
        "documents_required",
        "selection_process",
        "renewal_requirements",
    ]
    for field in fields:
        b: FieldValue = getattr(base, field)
        d: FieldValue = getattr(donor, field)
        if (
            (not b.value or b.value == "Not specified")
            and d.value
            and d.value != "Not specified"
            and d.evidence is not None
        ):
            setattr(base, field, d)
            filled += 1
    # Prefer richer application URL from donor if base is only portal home
    if donor.application_url and (
        not base.application_url or base.application_url.rstrip("/") == "https://scholarships.gov.in"
    ):
        if "scholarship" in donor.application_url or "ugc.gov.in" in donor.application_url:
            base.application_url = donor.application_url
    return filled


def enrich_batch(records: list[ScholarshipRecord]) -> int:
    """Within one crawl batch, enrich thinner records from richer same-name donors."""
    by_norm: dict[str, list[ScholarshipRecord]] = {}
    for r in records:
        by_norm.setdefault(_norm(r.name), []).append(r)

    total = 0
    for group in by_norm.values():
        if len(group) < 2:
            continue
        # Prefer donor with evidenced amount, else most evidenced fields
        def richness(r: ScholarshipRecord) -> int:
            n = 0
            for f in (
                r.amount_benefit,
                r.income_criteria,
                r.age_criteria,
                r.eligibility,
                r.academic_requirements,
            ):
                if f.value and f.value != "Not specified" and f.evidence:
                    n += 1
            return n

        donor = max(group, key=richness)
        if richness(donor) == 0:
            continue
        for r in group:
            if r is donor:
                continue
            total += merge_evidenced_fields(r, donor)
    return total
