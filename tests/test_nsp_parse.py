from scholarship_intel.extract.parsers import extract_nsp_listing

SAMPLE = """
<html><body>
<h6>AICTE - Pragati Scholarship Scheme For Girl Students ( Technical Degree) (Merit Based Scheme)</h6>
<p>Scheme Open from : 01-06-2026 Student Application Open till : 31-10-2026</p>
<h6>PM-USP – Central Sector Scheme Of Scholarship For College And University Students (CSSS) (Merit Based Scheme)</h6>
<p>Scheme Open from (for Renewal): 01-06-2026 Student Application Closed on : 30-09-2026</p>
</body></html>
"""


def test_extract_nsp():
    recs = extract_nsp_listing(SAMPLE, "https://scholarships.gov.in/All-Scholarships")
    assert len(recs) >= 2
    names = {r.name for r in recs}
    assert any("Pragati" in n for n in names)
    pragati = next(r for r in recs if "Pragati" in r.name)
    assert pragati.closing_date.value == "2026-10-31"
    assert pragati.application_url == "https://scholarships.gov.in/"
    csss = next(r for r in recs if "CSSS" in r.name or "Central Sector" in r.name)
    assert csss.lifecycle_status.value in ("EXPIRED", "EXPIRING_SOON", "ACTIVE")
