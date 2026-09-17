"""
Schema for per-tenant client configuration.

Why this is its own Pydantic model, separate from ClaimDocument: the two
have completely different lifecycles. ClaimDocument is produced fresh
per-request. ClientConfig is authored once by (in a real system) a
solutions engineer onboarding a new client, checked into version control,
and read many times. Validating it with Pydantic at LOAD time - not at
first use, buried three calls deep - means a typo'd YAML file fails loud
and immediately, not silently in production on whatever request happens
to trigger it first.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict

from app.models.schemas import DocumentType


class ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    display_name: str

    accepted_document_types: list[DocumentType] = Field(
        description="Document types this tenant's pipeline is configured to handle. "
        "A document classified as a type NOT in this list should be flagged, not "
        "silently processed against a schema nobody agreed this tenant needs.",
    )

    review_threshold: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence below which an extraction routes to human review "
        "instead of auto-approval. Not used yet (Week 2 territory) but validated "
        "now so a bad value fails at config-load time, not silently at review time.",
    )

    field_label_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Tenant-specific display names for canonical field names "
        "(e.g. this tenant calls 'policy_number' a 'Member ID').",
    )
