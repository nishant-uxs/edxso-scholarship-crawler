from scholarship_intel.extract.documents import extract_from_document
from scholarship_intel.models import SourceType


SAMPLE = """
Reliance Foundation Undergraduate Scholarships

To be eligible you must be an Indian citizen residing in India.
Have passed Class 12 with a minimum of 60% marks.
Have a household income of 15 lakh or less per annum.

Scholarship of up to Rs. 2 lakhs for UG students.
The deadline to submit your application is 11:59 PM IST on Monday, 5 October 2026.
Apply at https://www.scholarships.reliancefoundation.org/
"""


def test_extract_reliance_faq_text():
    rec = extract_from_document(
        SAMPLE,
        "https://www.scholarships.reliancefoundation.org/assets/pdf/UG_FAQ.pdf",
        SourceType.CORPORATE_CSR,
    )
    assert rec is not None
    assert "Reliance" in rec.name
    assert rec.amount_benefit.value != "Not specified"
    assert rec.closing_date.value == "2026-10-05"
    assert rec.income_criteria.value != "Not specified"
