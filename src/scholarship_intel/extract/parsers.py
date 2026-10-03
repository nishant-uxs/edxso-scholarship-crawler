"""Deterministic extractors - never invent missing fields."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scholarship_intel.discovery.classify import classify_source_type, domain_of
from scholarship_intel.models import FieldValue, LifecycleStatus, ScholarshipRecord, SourceType

DATE_RE = re.compile(
    r"(?P<d>\d{1,2})[-/.](?P<m>\d{1,2})[-/.](?P<y>\d{4})",
    re.I,
)
AMOUNT_RE = re.compile(
    r"(?:Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)\s*(?:/-)?(?:\s*(?:per\s+annum|/year|p\.?a\.?|pm|per\s+month))?",
    re.I,
)
AGE_RE = re.compile(r"age\s*(?:limit\s*(?:is|:)?\s*)?(\d{1,2})\s*years?", re.I)
INCOME_RE = re.compile(
    r"(?:family\s+annual\s+income|income(?:\s+limit)?|TFAI)[^\n.]{0,80}?"
    r"(?:upto|up to|within|less than|below|:)?\s*"
    r"(?:Rs\.?\s*)?([\d.]+\s*(?:lacs?|lakhs?|L))",
    re.I,
)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:120] or "scholarship"


def parse_date_dmy(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = int(m.group("d")), int(m.group("m")), int(m.group("y"))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def format_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def snippet_around(text: str, needle: str, window: int = 120) -> str:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return text[:window]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(needle) + window)
    return " ".join(text[start:end].split())


def fv(value: str | None, field: str, url: str, text: str, needle: str | None = None) -> FieldValue:
    if not value or not str(value).strip():
        return FieldValue.not_specified()
    snip = snippet_around(text, needle or value[:40])
    return FieldValue.specified(str(value).strip(), field, url, snip)


def lifecycle_from_dates(opening: date | None, closing: date | None, today: date | None = None) -> LifecycleStatus:
    today = today or date.today()
    if closing and closing < today:
        return LifecycleStatus.EXPIRED
    if closing and (closing - today).days <= 30:
        return LifecycleStatus.EXPIRING_SOON
    if opening or closing:
        return LifecycleStatus.ACTIVE
    return LifecycleStatus.REVIEW_REQUIRED


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"|")
    return h.hexdigest()[:16]


SCHEME_BLOCK_RE = re.compile(
    r"######\s*(.+?)\s*\n\s*((?:Scheme Open from|Student Application)[\s\S]*?)(?=\n######|\Z)",
    re.I,
)


def extract_nsp_listing(html: str, page_url: str) -> list[ScholarshipRecord]:
    soup = BeautifulSoup(html, "lxml")
    records: list[ScholarshipRecord] = []

    headings = soup.find_all(["h6", "h5", "h4"])
    for h in headings:
        name = h.get_text(" ", strip=True)
        if not name or len(name) < 8:
            continue
        # NSP scheme cards use h6 titles; skip page chrome
        if name.lower().startswith("schemes on nsp"):
            continue
        if not any(
            k in name.lower()
            for k in ("scholarship", "fellowship", "scheme", "stipend", "financial assistance")
        ):
            continue

        # Collect text from following siblings AND the card parent (NSP puts dates in spans).
        chunks: list[str] = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) in ("h6", "h5", "h4", "h3"):
                break
            if getattr(sib, "name", None) in ("script", "style"):
                continue
            if hasattr(sib, "get_text"):
                t = sib.get_text(" ", strip=True)
            else:
                t = str(sib).strip()
                if t.startswith("<!--"):
                    continue
            if t:
                chunks.append(t)
        block = " ".join(chunks)
        if "Open" not in block and "Application" not in block:
            parent = h.parent
            if parent is not None:
                block = parent.get_text(" ", strip=True)
        if "Open" not in block and "Application" not in block:
            continue
        rec = _record_from_nsp_block(name, block, page_url)
        if rec:
            records.append(rec)

    if len(records) < 5:
        text = soup.get_text("\n", strip=True)
        for m in SCHEME_BLOCK_RE.finditer("###### " + text.replace("\r", "")):
            name = m.group(1).strip()
            block = m.group(2).strip()
            rec = _record_from_nsp_block(name, block, page_url)
            if rec:
                records.append(rec)

    seen: set[str] = set()
    unique: list[ScholarshipRecord] = []
    for r in records:
        if r.slug in seen:
            continue
        seen.add(r.slug)
        unique.append(r)
    return unique


def _record_from_nsp_block(name: str, block: str, page_url: str) -> ScholarshipRecord | None:
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) < 8:
        return None

    provider = "Government of India (via NSP)"
    if name.upper().startswith("AICTE"):
        provider = "AICTE / Ministry of Education"
    elif name.upper().startswith("UGC") or "Post Graduate Studies" in name or "Ishan Uday" in name:
        provider = "University Grants Commission (UGC)"
    elif name.upper().startswith("ICAR"):
        provider = "Indian Council of Agricultural Research (ICAR)"
    elif "Prime Minister" in name or name.startswith("PM "):
        provider = "Government of India"
    elif "Beedi" in name or "Cine" in name:
        provider = "Ministry of Labour & Employment"
    elif "Disabilit" in name:
        provider = "Department of Empowerment of Persons with Disabilities"
    elif "ST Students" in name or "Schedule Tribe" in name:
        provider = "Ministry of Tribal Affairs"
    elif "SC Students" in name:
        provider = "Ministry of Social Justice and Empowerment"
    elif "OBC" in name or "YASASVI" in name:
        provider = "Ministry of Social Justice and Empowerment"
    elif "NER" in name or "NEC Merit" in name:
        provider = "Ministry of Development of North Eastern Region / NEC"
    elif "Railways" in name:
        provider = "Ministry of Railways"
    elif "Renewable Energy" in name:
        provider = "Ministry of New and Renewable Energy"
    elif "Statistical Institute" in name:
        provider = "Indian Statistical Institute"

    gender = None
    if re.search(r"\bgirl\b", name, re.I):
        gender = "Female (girl students)"
    category = None
    for cat in ("SC", "ST", "OBC", "EBC", "DNT", "Minority"):
        if re.search(rf"\b{cat}\b", name, re.I):
            category = (category + ", " if category else "") + cat

    domicile = None
    if re.search(r"Jammu|Kashmir|Ladakh", name, re.I):
        domicile = "Jammu & Kashmir / Ladakh"
    elif re.search(r"\bNER\b|North Eastern", name, re.I):
        domicile = "North Eastern Region"

    education = None
    if re.search(r"pre[\s-]?matric", name, re.I):
        education = "Pre-Matric"
    elif re.search(r"post[\s-]?matric|college|university|PG|post graduate|degree|diploma", name, re.I):
        education = "Post-Matric / Higher education"
    if re.search(r"Technical Degree", name, re.I):
        education = "Technical Degree (AICTE)"
    elif re.search(r"Technical Diploma", name, re.I):
        education = "Technical Diploma (AICTE)"

    open_m = re.search(
        r"Scheme\s+Open\s+from(?:\s*\([^)]*\))?\s*:\s*([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4})",
        block,
        re.I,
    )
    close_m = re.search(
        r"Student\s+Application\s+(?:Open\s+till|Closed\s+on)(?:\s*\([^)]*\))?\s*:\s*([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4})",
        block,
        re.I,
    )
    opening = parse_date_dmy(open_m.group(1)) if open_m else None
    closing = parse_date_dmy(close_m.group(1)) if close_m else None
    closed_explicit = bool(re.search(r"Closed on", block, re.I))

    eligibility_bits = []
    if "(Merit Based Scheme)" in name:
        eligibility_bits.append("Merit-based scheme (as classified on NSP)")
    if "(Welfare Based Scheme)" in name:
        eligibility_bits.append("Welfare-based scheme (as classified on NSP)")
    if gender:
        eligibility_bits.append(gender)
    if category:
        eligibility_bits.append(f"Category focus: {category}")
    if domicile:
        eligibility_bits.append(f"Domicile: {domicile}")
    eligibility = "; ".join(eligibility_bits) if eligibility_bits else None

    status = lifecycle_from_dates(opening, closing)
    if closed_explicit and closing and closing <= date.today():
        status = LifecycleStatus.EXPIRED

    text = f"{name}\n{block}"
    slug = slugify(name)

    return ScholarshipRecord(
        slug=slug,
        name=re.sub(r"\s*\((?:Merit|Welfare) Based Scheme\)\s*$", "", name, flags=re.I).strip(),
        provider=provider,
        official_source_url=page_url,
        application_url="https://scholarships.gov.in/",
        source_type=SourceType.GOVERNMENT_PORTAL,
        discovery_url=page_url,
        amount_benefit=FieldValue.not_specified(),
        eligibility=fv(
            eligibility,
            "eligibility",
            page_url,
            text,
            eligibility_bits[0] if eligibility_bits else name[:30],
        ),
        academic_requirements=FieldValue.not_specified(),
        education_level=fv(education, "education_level", page_url, text, education or ""),
        income_criteria=FieldValue.not_specified(),
        age_criteria=FieldValue.not_specified(),
        gender_criteria=fv(gender, "gender_criteria", page_url, text, gender or ""),
        category_criteria=fv(category, "category_criteria", page_url, text, category or ""),
        domicile_state=fv(domicile, "domicile_state", page_url, text, domicile or ""),
        institution_requirements=FieldValue.not_specified(),
        opening_date=fv(
            format_date(opening),
            "opening_date",
            page_url,
            text,
            open_m.group(1) if open_m else "",
        ),
        closing_date=fv(
            format_date(closing),
            "closing_date",
            page_url,
            text,
            close_m.group(1) if close_m else "",
        ),
        documents_required=FieldValue.not_specified(),
        selection_process=fv(
            "Merit Based"
            if "Merit Based" in name
            else ("Welfare Based" if "Welfare Based" in name else None),
            "selection_process",
            page_url,
            text,
        ),
        renewal_requirements=FieldValue.not_specified(),
        lifecycle_status=status,
        last_verified_at=datetime.utcnow(),
        content_hash=content_hash(name, format_date(opening) or "", format_date(closing) or ""),
        raw_excerpt=block[:1500],
        extra={"listing_title": name, "nsp_block": True},
    )


_JUNK_TITLES = {
    "about us",
    "education",
    "students students",
    "welcome to ugc, new delhi, india",
    "national scholarship portal",
    "nsp : national scholarship portal",
    "students development schemes",
    "scholarship eligibility check",
    "scheme-wise nodal officers",
}


def extract_detail_page(
    html: str, page_url: str, source_type: SourceType | None = None
) -> ScholarshipRecord | None:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    if "scholarship" not in text.lower() and "fellowship" not in text.lower():
        return None

    name = None
    # Prefer explicit scheme name label (UGC pages)
    m = re.search(r"Name of the Scheme:\s*(.+)", text, re.I)
    if m:
        name = m.group(1).strip().split("\n")[0]
    if not name:
        for sel in ("h1", "h2", ".title"):
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 5:
                name = el.get_text(" ", strip=True)
                break
    if not name:
        name = soup.title.get_text(strip=True) if soup.title else None
    if not name or len(name) < 5:
        return None
    if name.strip().lower() in _JUNK_TITLES:
        return None
    # Prefer h3 section titles like "MCM Scholarship" on university pages
    for h3 in soup.find_all(["h3", "h2", "h1"]):
        ht = h3.get_text(" ", strip=True)
        if re.search(r"scholarship|fellowship", ht, re.I) and 5 < len(ht) < 120:
            name = ht
            break
    if not any(
        k in name.lower() for k in ("scholarship", "fellowship", "scheme", "stipend", "award", "mcm", "fbm")
    ):
        if not m:
            return None

    provider = "Not specified"
    host = domain_of(page_url)
    if "ugc.gov.in" in host:
        provider = "University Grants Commission (UGC)"
    elif "aicte" in host:
        provider = "AICTE"
    elif "iitk.ac.in" in host:
        provider = "Indian Institute of Technology Kanpur"
    elif host.endswith(".ac.in"):
        provider = host.replace(".ac.in", "").upper()
    elif "reliancefoundation" in host:
        provider = "Reliance Foundation"
    elif "tatatrusts" in host:
        provider = "Tata Trusts"

    amount = None
    am = AMOUNT_RE.search(text)
    if am:
        amount = f"Rs. {am.group(1)}"
        if re.search(r"per\s+annum|p\.?a\.?", am.group(0), re.I):
            amount += " per annum"
        elif re.search(r"\bpm\b|per\s+month", am.group(0), re.I):
            amount += " per month"

    age = None
    ag = AGE_RE.search(text)
    if ag:
        age = f"{ag.group(1)} years"

    income = None
    im = INCOME_RE.search(text)
    if im:
        income = f"Family income up to {im.group(1).strip()}"

    eligibility = None
    em = re.search(
        r"Eligibility:\s*(.+?)(?:\n[A-Z][a-z]+ ?:|\nSlots:|\nTenure:|\nFinancial)",
        text,
        re.S | re.I,
    )
    if em:
        eligibility = " ".join(em.group(1).split())[:800]
    elif re.search(r"subject to the following criteria|eligible to receive", text, re.I):
        # University pages: take a short grounded snippet
        sm = re.search(
            r"((?:An undergraduate|The students belonging|eligible to receive)[^\n]{20,220})",
            text,
            re.I,
        )
        if sm:
            eligibility = sm.group(1).strip()

    academic = None
    if re.search(r"CPI of 6\.5|minimum CPI", text, re.I):
        academic = "CPI / academic performance criteria stated on page"
    elif re.search(r"first year of PG|postgraduate", text, re.I):
        academic = "Admitted to first year of recognised PG programme (as stated on page)"

    education = None
    if re.search(r"postgraduate|PG degree|P\.G\.", text, re.I):
        education = "Postgraduate"
    elif re.search(r"undergraduate|UG\b|B\.Tech|4-year", text, re.I):
        education = "Undergraduate"

    category = None
    if re.search(r"SC/ST categories only|belonging to the SC/ST", text, re.I):
        category = "SC/ST"

    app_url = page_url
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = a.get_text(" ", strip=True).lower()
        if "scholarships.gov.in" in href or "apply" in label:
            app_url = urljoin(page_url, href)
            break
    if "scholarships.gov.in" in text and "scholarships.gov.in" not in (app_url or ""):
        app_url = "https://scholarships.gov.in/"

    st = source_type or classify_source_type(page_url)
    slug = slugify(name) + "-" + content_hash(page_url)[:6]

    return ScholarshipRecord(
        slug=slug,
        name=name[:300],
        provider=provider,
        official_source_url=page_url,
        application_url=app_url,
        source_type=st,
        discovery_url=page_url,
        amount_benefit=fv(amount, "amount_benefit", page_url, text, amount or ""),
        eligibility=fv(eligibility, "eligibility", page_url, text, eligibility[:40] if eligibility else "eligible"),
        academic_requirements=fv(academic, "academic_requirements", page_url, text, academic or ""),
        education_level=fv(education, "education_level", page_url, text, education or ""),
        income_criteria=fv(income, "income_criteria", page_url, text, income or ""),
        age_criteria=fv(age, "age_criteria", page_url, text, age or ""),
        gender_criteria=FieldValue.not_specified(),
        category_criteria=fv(category, "category_criteria", page_url, text, category or ""),
        domicile_state=FieldValue.not_specified(),
        institution_requirements=fv(
            "IIT Kanpur enrolled students" if "iitk.ac.in" in host else (
                "Eligible university/college/institution as per scheme"
                if "eligible university" in text.lower()
                else None
            ),
            "institution_requirements",
            page_url,
            text,
            "IIT Kanpur" if "iitk" in host else "eligible university",
        ),
        opening_date=FieldValue.not_specified(),
        closing_date=FieldValue.not_specified(),
        documents_required=FieldValue.not_specified(),
        selection_process=FieldValue.not_specified(),
        renewal_requirements=fv(
            "2 years tenure" if re.search(r"Tenure:\s*2 years", text, re.I) else None,
            "renewal_requirements",
            page_url,
            text,
            "Tenure",
        ),
        lifecycle_status=LifecycleStatus.ACTIVE if amount or eligibility or income else LifecycleStatus.REVIEW_REQUIRED,
        last_verified_at=datetime.utcnow(),
        content_hash=content_hash(name, amount or "", eligibility or "", income or ""),
        raw_excerpt=text[:2000],
    )


def discover_links(html: str, base_url: str, official_suffixes: list[str]) -> list[str]:
    from scholarship_intel.discovery.classify import is_aggregator, is_official_domain

    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        label = (a.get_text(" ", strip=True) + " " + href).lower()
        if not any(
            k in label
            for k in ("scholarship", "fellowship", "scheme", "financial assistance", "stipend")
        ):
            continue
        if is_aggregator(href, ["buddy4study.com", "wikipedia.org", "facebook.com", "twitter.com"]):
            continue
        if is_official_domain(href, official_suffixes) or domain_of(href) == domain_of(base_url):
            parsed = urlparse(href)
            clean = parsed._replace(fragment="").geturl()
            out.append(clean)
    seen: set[str] = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:40]
