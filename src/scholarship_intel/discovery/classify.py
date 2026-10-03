"""Source classification - official vs aggregator."""

from __future__ import annotations

from urllib.parse import urlparse

from scholarship_intel.models import SourceType


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_official_domain(url: str, official_suffixes: list[str]) -> bool:
    host = domain_of(url)
    for suf in official_suffixes:
        s = suf.lstrip(".").lower()
        if host == s or host.endswith("." + s) or host.endswith(s):
            return True
    return False


def is_aggregator(url: str, aggregator_domains: list[str]) -> bool:
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in aggregator_domains)


def classify_source_type(url: str, hint: str | None = None) -> SourceType:
    if hint:
        try:
            return SourceType(hint)
        except ValueError:
            pass
    host = domain_of(url)
    if "scholarships.gov.in" in host:
        return SourceType.GOVERNMENT_PORTAL
    if host.endswith(".gov.in") or host.endswith(".nic.in"):
        return SourceType.GOVERNMENT
    if host.endswith(".ac.in") or host.endswith(".edu.in"):
        return SourceType.UNIVERSITY
    if "aicte" in host:
        return SourceType.GOVERNMENT
    if any(x in host for x in ("reliancefoundation", "infosys", "tcs", "wipro", "google")):
        return SourceType.CORPORATE_CSR
    if any(x in host for x in ("tatatrusts", "ladytatatrust", "trust", "foundation", "ngo")):
        return SourceType.NGO_TRUST
    return SourceType.UNKNOWN
