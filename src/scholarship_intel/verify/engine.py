"""
Evidence-based confidence scoring.

Critical rule from assignment: Do NOT ask an LLM to invent a confidence number.
Score is a transparent weighted sum of observable checks.
"""

from __future__ import annotations

from datetime import date, datetime

from scholarship_intel.discovery.classify import is_aggregator, is_official_domain
from scholarship_intel.models import (
    ConfidenceBreakdown,
    FieldValue,
    LifecycleStatus,
    ScholarshipRecord,
    SourceType,
    VerificationLabel,
)

# Weights sum conceptually to 100; each factor contributes its weight when true.
# Max theoretical = 105; capped at 100. A typical NSP listing with
# official domain > live page > apply URL > evidenced eligibility > dates
# scores >=95 without inventing amount fields.
WEIGHTS = {
    "official_source_domain": 28.0,
    "present_on_official_page": 18.0,
    "has_application_url": 10.0,
    "eligibility_evidenced": 12.0,
    "deadline_evidenced": 12.0,
    "amount_evidenced": 6.0,
    "income_evidenced": 4.0,
    "not_aggregator_primary": 8.0,
    "source_type_known": 3.0,
    "information_current": 5.0,
}


def _has_evidence(fv: FieldValue) -> bool:
    return bool(
        fv
        and fv.value
        and fv.value != "Not specified"
        and fv.evidence is not None
        and fv.evidence.snippet
    )


def score_scholarship(
    rec: ScholarshipRecord,
    *,
    official_suffixes: list[str],
    aggregator_domains: list[str],
    page_fetch_ok: bool = True,
) -> ConfidenceBreakdown:
    factors: dict[str, float] = {}
    reasons: list[str] = []

    official = is_official_domain(rec.official_source_url, official_suffixes)
    if official:
        factors["official_source_domain"] = WEIGHTS["official_source_domain"]
        reasons.append("Official/primary domain matched allowlist (.gov.in / .ac.in / known provider).")
    else:
        factors["official_source_domain"] = 0.0
        reasons.append("Primary URL is not on the official-domain allowlist.")

    if page_fetch_ok and rec.name:
        factors["present_on_official_page"] = WEIGHTS["present_on_official_page"]
        reasons.append("Scholarship name extracted from a successfully fetched official page.")
    else:
        factors["present_on_official_page"] = 0.0
        reasons.append("Could not confirm presence on a live official page.")

    if rec.application_url:
        factors["has_application_url"] = WEIGHTS["has_application_url"]
        reasons.append(f"Application URL retained: {rec.application_url}")
    else:
        factors["has_application_url"] = 0.0
        reasons.append("No application URL found on source.")

    if _has_evidence(rec.eligibility):
        factors["eligibility_evidenced"] = WEIGHTS["eligibility_evidenced"]
        reasons.append("Eligibility supported by source evidence snippet.")
    else:
        factors["eligibility_evidenced"] = 0.0
        reasons.append("Eligibility not evidenced (stored as Not specified or no snippet).")

    if _has_evidence(rec.closing_date) or _has_evidence(rec.opening_date):
        factors["deadline_evidenced"] = WEIGHTS["deadline_evidenced"]
        reasons.append("Opening/closing date supported by source evidence.")
    else:
        factors["deadline_evidenced"] = 0.0
        reasons.append("No evidenced deadline on official source.")

    if _has_evidence(rec.amount_benefit):
        factors["amount_evidenced"] = WEIGHTS["amount_evidenced"]
        reasons.append("Amount/benefit evidenced from source text.")
    else:
        factors["amount_evidenced"] = 0.0
        reasons.append("Amount not specified on source - left as Not specified (no hallucination).")

    if _has_evidence(rec.income_criteria):
        factors["income_evidenced"] = WEIGHTS["income_evidenced"]
        reasons.append("Income criteria evidenced from source text.")
    else:
        factors["income_evidenced"] = 0.0
        reasons.append("Income criteria not specified on source.")

    if not is_aggregator(rec.official_source_url, aggregator_domains) and rec.source_type != SourceType.AGGREGATOR:
        factors["not_aggregator_primary"] = WEIGHTS["not_aggregator_primary"]
        reasons.append("Primary source is not an aggregator/blog.")
    else:
        factors["not_aggregator_primary"] = 0.0
        reasons.append("Primary source looks like an aggregator - cannot VERIFIED.")

    if rec.source_type not in (SourceType.UNKNOWN, SourceType.AGGREGATOR):
        factors["source_type_known"] = WEIGHTS["source_type_known"]
        reasons.append(f"Source type classified as {rec.source_type.value}.")
    else:
        factors["source_type_known"] = 0.0
        reasons.append("Source type unknown.")

    # Currency: active / expiring with a closing date in the future, or detail page with evidence
    current = False
    if rec.lifecycle_status in (LifecycleStatus.ACTIVE, LifecycleStatus.EXPIRING_SOON):
        current = True
    if _has_evidence(rec.closing_date):
        try:
            d = date.fromisoformat(rec.closing_date.value)  # type: ignore[arg-type]
            if d >= date.today():
                current = True
        except Exception:
            pass
    if current:
        factors["information_current"] = WEIGHTS["information_current"]
        reasons.append(f"Lifecycle status {rec.lifecycle_status.value} treated as current.")
    else:
        factors["information_current"] = 0.0
        reasons.append(f"Lifecycle {rec.lifecycle_status.value} - not scored as current.")

    score = round(sum(factors.values()), 1)
    # Cap at 100
    score = min(100.0, score)

    # Hard gates: never VERIFIED if aggregator primary or non-official
    label = VerificationLabel.VERIFIED if score >= 95.0 else VerificationLabel.REVIEW_REQUIRED
    if not official or is_aggregator(rec.official_source_url, aggregator_domains):
        label = VerificationLabel.REVIEW_REQUIRED
        if score >= 95.0:
            score = 94.0
            reasons.append("Hard gate: non-official/aggregator primary - capped below VERIFIED.")

    return ConfidenceBreakdown(score=score, label=label, factors=factors, reasons=reasons)


def enrich_lifecycle(rec: ScholarshipRecord) -> LifecycleStatus:
    """Recompute lifecycle from evidenced closing date."""
    if rec.lifecycle_status == LifecycleStatus.NO_LONGER_VERIFIABLE:
        return rec.lifecycle_status
    closing = rec.closing_date.value if rec.closing_date else None
    if closing and closing != "Not specified":
        try:
            d = date.fromisoformat(closing)
            today = date.today()
            if d < today:
                return LifecycleStatus.EXPIRED
            if (d - today).days <= 30:
                return LifecycleStatus.EXPIRING_SOON
            return LifecycleStatus.ACTIVE
        except ValueError:
            pass
    return rec.lifecycle_status
