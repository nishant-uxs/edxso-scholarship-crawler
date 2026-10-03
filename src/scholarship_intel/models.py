"""Scholarship schema with evidence-traced fields."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    GOVERNMENT = "government"
    GOVERNMENT_PORTAL = "government_portal"
    UNIVERSITY = "university"
    CORPORATE_CSR = "corporate_csr"
    NGO_TRUST = "ngo_trust"
    INTERNATIONAL = "international"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


class VerificationLabel(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_LONGER_VERIFIABLE = "NO_LONGER_VERIFIABLE"


class Evidence(BaseModel):
    field: str
    value: str
    source_url: str
    snippet: str
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


class FieldValue(BaseModel):
    value: str | None = None
    evidence: Evidence | None = None

    @classmethod
    def specified(cls, value: str, field: str, source_url: str, snippet: str) -> FieldValue:
        return cls(
            value=value,
            evidence=Evidence(field=field, value=value, source_url=source_url, snippet=snippet[:500]),
        )

    @classmethod
    def not_specified(cls) -> FieldValue:
        return cls(value="Not specified", evidence=None)


class ConfidenceBreakdown(BaseModel):
    score: float  # 0-100
    label: VerificationLabel
    factors: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class ScholarshipRecord(BaseModel):
    id: str | None = None
    slug: str
    name: str
    provider: str
    official_source_url: str
    application_url: str | None = None
    source_type: SourceType
    discovery_url: str | None = None

    amount_benefit: FieldValue = Field(default_factory=FieldValue.not_specified)
    eligibility: FieldValue = Field(default_factory=FieldValue.not_specified)
    academic_requirements: FieldValue = Field(default_factory=FieldValue.not_specified)
    education_level: FieldValue = Field(default_factory=FieldValue.not_specified)
    income_criteria: FieldValue = Field(default_factory=FieldValue.not_specified)
    age_criteria: FieldValue = Field(default_factory=FieldValue.not_specified)
    gender_criteria: FieldValue = Field(default_factory=FieldValue.not_specified)
    category_criteria: FieldValue = Field(default_factory=FieldValue.not_specified)
    domicile_state: FieldValue = Field(default_factory=FieldValue.not_specified)
    institution_requirements: FieldValue = Field(default_factory=FieldValue.not_specified)
    opening_date: FieldValue = Field(default_factory=FieldValue.not_specified)
    closing_date: FieldValue = Field(default_factory=FieldValue.not_specified)
    documents_required: FieldValue = Field(default_factory=FieldValue.not_specified)
    selection_process: FieldValue = Field(default_factory=FieldValue.not_specified)
    renewal_requirements: FieldValue = Field(default_factory=FieldValue.not_specified)

    lifecycle_status: LifecycleStatus = LifecycleStatus.REVIEW_REQUIRED
    verification: ConfidenceBreakdown | None = None
    last_verified_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    content_hash: str | None = None
    raw_excerpt: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ChangeEvent(BaseModel):
    scholarship_id: str
    field: str
    old_value: str | None
    new_value: str | None
    detected_at: datetime
    source_url: str
    evidence_snippet: str | None = None


class CrawlRun(BaseModel):
    id: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    discovered: int = 0
    upserted: int = 0
    unchanged: int = 0
    changed: int = 0
    expired_marked: int = 0
    errors: list[str] = Field(default_factory=list)
