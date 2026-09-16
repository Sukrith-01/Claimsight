"""
Core data schemas for ClaimSight.

Design note (Day 1): this schema is intentionally the FIRST thing built,
before any extraction logic exists. Everything downstream - the LLM
extraction prompts, the confidence scorer, the review queue, the eval
harness - validates against this contract. Get the shape right here and
the rest of the system has something solid to build against; get it wrong
and every layer above inherits the mistake.

`ClaimDocument` is intentionally generic - it does NOT assume a specific
insurer's field names. Per-tenant field mapping lives in configs/*.yaml
and is applied by app/config/loader.py (Week 1, Day 4). This file defines
the canonical internal shape everything gets mapped TO.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class DocumentType(str, Enum):
    """What kind of source document this extraction came from."""
    ACCIDENT_REPORT = "accident_report"
    POLICY_DOCUMENT = "policy_document"
    MEDICAL_BILL = "medical_bill"
    UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    """Where a claim extraction sits in the human-in-the-loop workflow."""
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    CORRECTED = "corrected"


class Claimant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    date_of_birth: Optional[date] = None
    policy_number: Optional[str] = None


class IncidentDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_date: Optional[date] = None
    incident_description: Optional[str] = None
    location: Optional[str] = None


class BillingLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    billed_amount: Decimal
    diagnosis_code: Optional[str] = None


class FieldConfidence(BaseModel):
    """
    Per-field confidence score, not just one document-level score.

    Why per-field: a claim can be 95% confident on the claimant's name
    and 40% confident on the billed amount (e.g. a smudged scan). Routing
    the WHOLE document to review because one field is shaky wastes an
    adjuster's time; routing nothing because the average looks fine hides
    a real error. Per-field confidence lets Week 2's routing logic make
    that call at the right granularity.
    """
    model_config = ConfigDict(extra="forbid")

    field_name: str
    score: float = Field(ge=0.0, le=1.0)


class ClaimDocument(BaseModel):
    """
    Canonical extracted representation of one claim document.
    This is the object every other component in the system reads or writes.
    """
    model_config = ConfigDict(extra="forbid")

    document_id: str
    tenant_id: str
    document_type: DocumentType = DocumentType.UNKNOWN

    claimant: Optional[Claimant] = None
    incident: Optional[IncidentDetails] = None
    billing: list[BillingLineItem] = Field(default_factory=list)

    field_confidences: list[FieldConfidence] = Field(default_factory=list)
    overall_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW

    raw_text_excerpt: Optional[str] = Field(
        default=None,
        description="First ~500 chars of OCR/extracted text, kept for debugging and eval traceability.",
    )
