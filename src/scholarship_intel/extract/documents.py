"""Extract scholarship records from official HTML press pages and PDFs."""

from __future__ import annotations

import io
import re
from datetime import date, datetime

from scholarship_intel.discovery.classify import classify_source_type
from scholarship_intel.extract.parsers import (
    AMOUNT_RE,
    INCOME_RE,
    content_hash,
    format_date,
    fv,
    lifecycle_from_dates,
    parse_date_dmy,
    slugify,
)
from scholarship_intel.models import FieldValue, LifecycleStatus, ScholarshipRecord, SourceType

LAKH_AMOUNT_RE = re.compile(
    r"(?:up to\s+)?(?:Rs\.?|INR|₹|`)\s*([\d,.]+)\s*(?:/-)?\s*(lakh|lac|lakhs|lacs)",
    re.I,
)
DEADLINE_RE = re.compile(
    r"(?:deadline|last date|closing date|closed on|submit(?:\s+your)?\s+application)[^\n]{0,80}?"
    r"(?:is|:|on)?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4})",
    re.I,
)


def pdf_to_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages[:20]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _pick_amount(text: str) -> str | None:
    m = LAKH_AMOUNT_RE.search(text)
    if m:
        return f"Rs. {m.group(1)} {m.group(2)}"
    m2 = AMOUNT_RE.search(text)
    if m2:
        amt = f"Rs. {m2.group(1)}"
        if re.search(r"per\s+annum|p\.?a\.?", m2.group(0), re.I):
            amt += " per annum"
        elif re.search(r"\bpm\b|per\s+month", m2.group(0), re.I):
            amt += " per month"
        return amt
    # "Scholarship of up to Rs. 2 lakhs for UG and up to Rs. 6 lakhs for PG"
    multi = list(LAKH_AMOUNT_RE.finditer(text))
    if len(multi) >= 2:
        return f"UG up to Rs. {multi[0].group(1)} {multi[0].group(2)}; PG up to Rs. {multi[1].group(1)} {multi[1].group(2)}"
    return None


def _parse_english_date(text: str) -> date | None:
    # 5 October 2026 / October 5, 2026
    m = re.search(
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text,
        re.I,
    )
    if m:
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        return date(int(m.group(3)), months[m.group(2).lower()], int(m.group(1)))
    return parse_date_dmy(text)


_JUNK_NAME = re.compile(
    r"<|>|title>|href=|nsp\s*:|national scholarship portal$|login|register|"
    r"award schedule$|legacy cases|bureaus/|tbm-link|eligibility check|"
    r"^apply for scholarship$|copyright|privacy policy|terms.conditions|"
    r"eligibility criteria for the means grant program is$",
    re.I,
)


def extract_from_document(
    text: str,
    page_url: str,
    source_type: SourceType | None = None,
    title_hint: str | None = None,
) -> ScholarshipRecord | None:
    # Strip tags if HTML leaked into text
    if "<" in text and ">" in text:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(text, "lxml").get_text("\n", strip=True)
    if not text or len(text) < 80:
        return None
    if not re.search(r"scholarship|fellowship|means grant|financial (?:aid|assistance)", text, re.I):
        return None

    # Skip thin portal chrome pages
    if len(text) < 400 and "reliance" not in page_url.lower() and "tata" not in page_url.lower():
        if not re.search(r"Rs\.|INR|lakh|eligibility|deadline", text, re.I):
            return None

    name = title_hint
    if not name:
        for pat in (
            r"(Reliance Foundation(?:['']s)?(?: prestigious)? Scholarships?(?: 2026[-–]27)?)",
            r"(Reliance Foundation Undergraduate Scholarships?)",
            r"(Lady Meherbai D Tata Education Trust)",
            r"(Tata Trusts['']? Means Grant)",
            r"(Means Grant programme|Means Grant program)",
            r"(National Scholarship for Post Graduate Studies)",
            r"Name of the Scheme:\s*(.+)",
        ):
            m = re.search(pat, text, re.I)
            if m:
                name = m.group(1).strip()
                break
    if name and "eligibility criteria" in name.lower():
        name = "Tata Trusts Means Grant Programme"
    if "means grant" in (page_url + " " + (name or "")).lower() and (
        not name or "eligibility" in name.lower()
    ):
        name = "Tata Trusts Means Grant Programme"
    if not name:
        for line in text.splitlines():
            line = line.strip()
            if _JUNK_NAME.search(line):
                continue
            if re.search(r"scholarship|fellowship|means grant", line, re.I) and 12 < len(line) < 140:
                name = line
                break
    if not name or _JUNK_NAME.search(name):
        return None
    # Require at least one concrete fact for document extracts
    if not (
        re.search(r"Rs\.|INR|lakh|deadline|eligible|income|closed", text, re.I)
    ):
        return None

    st = source_type or classify_source_type(page_url)
    host = page_url.lower()
    provider = "Not specified"
    if "reliance" in host or "reliance" in name.lower():
        provider = "Reliance Foundation"
        st = SourceType.CORPORATE_CSR
    elif "tata" in host or "tata" in name.lower():
        provider = "Tata Trusts / Lady Meherbai D Tata Education Trust"
        st = SourceType.NGO_TRUST
    elif "ugc.gov.in" in host:
        provider = "University Grants Commission (UGC)"
        st = SourceType.GOVERNMENT

    amount = _pick_amount(text)
    income = None
    im = INCOME_RE.search(text)
    if im:
        income = f"Family income up to {im.group(1).strip()}"
    else:
        im2 = re.search(
            r"household income of\s*[`₹Rs\.]*\s*([\d.]+\s*lakh[s]?)\s*or less",
            text,
            re.I,
        )
        if im2:
            income = f"Household income {im2.group(1)} or less"

    eligibility = None
    em = re.search(
        r"(?:eligible|eligibility)[^\n]{0,40}?:?\s*(.{40,400})",
        text,
        re.I,
    )
    if em:
        eligibility = " ".join(em.group(1).split())[:700]
    elif re.search(r"Indian (?:citizen|women graduate)", text, re.I):
        sm = re.search(r"(Indian (?:citizen|women graduate)[^\n]{10,220})", text, re.I)
        if sm:
            eligibility = sm.group(1).strip()

    closing = None
    dm = DEADLINE_RE.search(text)
    if dm:
        closing = _parse_english_date(dm.group(1)) or parse_date_dmy(dm.group(1))
    if not closing:
        # "11:59 PM IST on Monday, 5 October 2026"
        dm2 = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
        if dm2 and re.search(r"deadline|last date|closed", text, re.I):
            closing = _parse_english_date(dm2.group(1))

    # Explicit closed announcements
    if re.search(r"now closed|will stand cancelled|no requests will be accepted after", text, re.I):
        if closing is None:
            # try find March 30, 2026 style
            closing = _parse_english_date(text)

    education = None
    if re.search(r"undergraduate|UG\b", text, re.I):
        education = "Undergraduate"
    if re.search(r"postgraduate|PG\b|higher education abroad", text, re.I):
        education = "Postgraduate" if education is None else "Undergraduate / Postgraduate"

    gender = None
    if re.search(r"Indian women graduate|women graduates", text, re.I):
        gender = "Female"

    app_url = None
    for m in re.finditer(r"https?://[^\s)\"']+", text):
        u = m.group(0).rstrip(".,;")
        if "scholarship" in u.lower() or "reliancefoundation" in u.lower() or "tatatrusts" in u.lower():
            app_url = u
            break
    if not app_url and "scholarships.reliancefoundation.org" in text:
        app_url = "https://www.scholarships.reliancefoundation.org/"
    if not app_url:
        app_url = page_url

    status = lifecycle_from_dates(None, closing)
    if re.search(r"now closed|request for fresh applications.*?closed", text, re.I):
        status = LifecycleStatus.EXPIRED

    slug = slugify(name) + "-" + content_hash(page_url)[:6]
    return ScholarshipRecord(
        slug=slug,
        name=name[:300],
        provider=provider,
        official_source_url=page_url,
        application_url=app_url,
        source_type=st,
        discovery_url=page_url,
        amount_benefit=fv(amount, "amount_benefit", page_url, text, amount or "Rs"),
        eligibility=fv(eligibility, "eligibility", page_url, text, "eligible"),
        academic_requirements=fv(
            "Class 12 minimum 60%" if re.search(r"60%\s*marks", text, re.I) else None,
            "academic_requirements",
            page_url,
            text,
            "60%",
        ),
        education_level=fv(education, "education_level", page_url, text, education or ""),
        income_criteria=fv(income, "income_criteria", page_url, text, income or ""),
        age_criteria=fv(
            "No age limit" if re.search(r"no age limit", text, re.I) else None,
            "age_criteria",
            page_url,
            text,
            "age limit",
        ),
        gender_criteria=fv(gender, "gender_criteria", page_url, text, gender or ""),
        category_criteria=FieldValue.not_specified(),
        domicile_state=FieldValue.not_specified(),
        institution_requirements=fv(
            "NAAC-accredited or UGC-recognised institution in India"
            if re.search(r"NAAC-accredited|UGC-recognised", text, re.I)
            else None,
            "institution_requirements",
            page_url,
            text,
            "NAAC",
        ),
        opening_date=FieldValue.not_specified(),
        closing_date=fv(format_date(closing), "closing_date", page_url, text, format_date(closing) or ""),
        documents_required=FieldValue.not_specified(),
        selection_process=fv(
            "Aptitude assessment + financial background"
            if re.search(r"aptitude", text, re.I)
            else ("Interview" if re.search(r"interview", text, re.I) else None),
            "selection_process",
            page_url,
            text,
            "aptitude",
        ),
        renewal_requirements=FieldValue.not_specified(),
        lifecycle_status=status,
        last_verified_at=datetime.utcnow(),
        content_hash=content_hash(name, amount or "", format_date(closing) or ""),
        raw_excerpt=text[:2000],
    )
