from scholarship_intel.models import FieldValue, LifecycleStatus, ScholarshipRecord, SourceType
from scholarship_intel.verify.engine import score_scholarship


def test_official_nsp_scores_verified():
    rec = ScholarshipRecord(
        slug="test-scheme",
        name="AICTE - Pragati Scholarship Scheme For Girl Students",
        provider="AICTE",
        official_source_url="https://scholarships.gov.in/All-Scholarships",
        application_url="https://scholarships.gov.in/",
        source_type=SourceType.GOVERNMENT_PORTAL,
        eligibility=FieldValue.specified(
            "Merit-based", "eligibility", "https://scholarships.gov.in/All-Scholarships", "Merit Based Scheme"
        ),
        closing_date=FieldValue.specified(
            "2026-10-31", "closing_date", "https://scholarships.gov.in/All-Scholarships", "31-10-2026"
        ),
        opening_date=FieldValue.specified(
            "2026-06-01", "opening_date", "https://scholarships.gov.in/All-Scholarships", "01-06-2026"
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    conf = score_scholarship(
        rec,
        official_suffixes=[".gov.in", "scholarships.gov.in"],
        aggregator_domains=["buddy4study.com"],
        page_fetch_ok=True,
    )
    assert conf.score >= 95
    assert conf.label.value == "VERIFIED"


def test_no_hallucinated_amount_is_ok():
    rec = ScholarshipRecord(
        slug="x",
        name="X",
        provider="Y",
        official_source_url="https://example.com/page",
        source_type=SourceType.UNKNOWN,
        amount_benefit=FieldValue.not_specified(),
    )
    assert rec.amount_benefit.value == "Not specified"
