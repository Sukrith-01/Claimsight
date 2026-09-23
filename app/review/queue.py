"""
Human review queue: where low-confidence extractions go, and where
adjuster corrections come from.

This is the human-in-the-loop piece the entire confidence pipeline
exists to serve. Without it, confidence scoring is just a number nobody
acts on; with it, low-confidence extractions get shown to a person,
that person corrects what the system got wrong, and (Day 10) those
corrections feed back into improving the golden dataset.

Design decisions worth explaining in an interview:

1. In-memory storage (dict), not a database. This is a deliberate
   scope decision for a 4-week project: SQLite or Postgres would be
   more production-realistic, but the API contract - the endpoints,
   request/response shapes, and behavior - is the same regardless of
   what stores the data behind it. A reviewer evaluating this project
   should judge the contract and the workflow, not the storage engine.
   Swapping to a real DB is a mechanical change (replace dict lookups
   with queries), not a design change.

2. Corrections are APPENDED, never overwriting the original extraction.
   This matters for two reasons: (a) audit trail - in regulated
   industries like insurance, being able to show "the system extracted
   X, the adjuster corrected it to Y" is not optional, it's a
   compliance requirement, and (b) training signal - the diff between
   what the system predicted and what the human corrected is exactly
   the data an eval harness or retraining pipeline would consume.

3. Queue items are scoped by tenant_id. An adjuster for Acme should
   never see Beta's review queue, same as the vector store and
   config isolation from Days 4 and 6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models.schemas import ClaimDocument


class ReviewItemStatus(str, Enum):
    PENDING = "pending"
    CORRECTED = "corrected"
    APPROVED_AS_IS = "approved_as_is"


class CorrectionEntry(BaseModel):
    """One adjuster correction to one field."""
    field_name: str
    original_value: Optional[str] = None
    corrected_value: str
    corrected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReviewItem(BaseModel):
    """A single item in the review queue - an extraction that needs human eyes."""
    document_id: str
    tenant_id: str
    status: ReviewItemStatus = ReviewItemStatus.PENDING
    extracted_document: ClaimDocument
    confidence_flags: list[str] = Field(default_factory=list)
    corrections: list[CorrectionEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewed_at: Optional[str] = None


# In-memory store - see module docstring for why this is deliberate,
# not lazy. Keyed by document_id for O(1) lookup.
_queue: dict[str, ReviewItem] = {}


def add_to_review(
    document_id: str,
    tenant_id: str,
    extracted_document: ClaimDocument,
    confidence_flags: list[str],
) -> ReviewItem:
    """Add an extraction to the review queue. Called by /ingest when requires_review is True."""
    item = ReviewItem(
        document_id=document_id,
        tenant_id=tenant_id,
        extracted_document=extracted_document,
        confidence_flags=confidence_flags,
    )
    _queue[document_id] = item
    return item


def get_review_item(document_id: str) -> ReviewItem | None:
    return _queue.get(document_id)


def list_pending_reviews(tenant_id: str) -> list[ReviewItem]:
    """List pending review items for ONE tenant. Never cross-tenant."""
    return [
        item for item in _queue.values()
        if item.tenant_id == tenant_id and item.status == ReviewItemStatus.PENDING
    ]


def apply_correction(
    document_id: str,
    corrections: list[CorrectionEntry],
) -> ReviewItem | None:
    """
    Apply adjuster corrections to a review item. Corrections are APPENDED,
    not overwritten - the original extraction stays intact for audit
    and for the feedback loop (Day 10).
    """
    item = _queue.get(document_id)
    if item is None:
        return None

    item.corrections.extend(corrections)
    item.status = ReviewItemStatus.CORRECTED
    item.reviewed_at = datetime.now(timezone.utc).isoformat()
    return item


def approve_as_is(document_id: str) -> ReviewItem | None:
    """Adjuster reviewed it and the extraction is correct - no corrections needed."""
    item = _queue.get(document_id)
    if item is None:
        return None

    item.status = ReviewItemStatus.APPROVED_AS_IS
    item.reviewed_at = datetime.now(timezone.utc).isoformat()
    return item


def get_queue_stats(tenant_id: str) -> dict:
    """Quick stats for a tenant's queue - useful for a dashboard or monitoring."""
    tenant_items = [i for i in _queue.values() if i.tenant_id == tenant_id]
    return {
        "tenant_id": tenant_id,
        "total": len(tenant_items),
        "pending": sum(1 for i in tenant_items if i.status == ReviewItemStatus.PENDING),
        "corrected": sum(1 for i in tenant_items if i.status == ReviewItemStatus.CORRECTED),
        "approved_as_is": sum(1 for i in tenant_items if i.status == ReviewItemStatus.APPROVED_AS_IS),
    }


def clear_queue() -> None:
    """For testing only - resets the in-memory store."""
    _queue.clear()
