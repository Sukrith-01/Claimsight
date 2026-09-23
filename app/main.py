"""
ClaimSight API entrypoint.

Day 1: health check + schema introspection.
Day 2: document ingestion (/ingest) with OCR.
Day 3: document classification wired into /ingest.
Day 4: per-tenant client config.
Day 6: chunking + embeddings + vector search.
Day 7: structured field extraction.
Day 8: multi-signal confidence scoring.
Day 9: human review queue. /ingest now auto-routes low-confidence
extractions into a review queue. New endpoints let an adjuster view
pending items, apply corrections, or approve as-is. Corrections are
appended (audit trail), never overwriting the original.
"""

import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from app.models.schemas import ClaimDocument, DocumentType
from app.ingestion.ocr import extract_text
from app.ingestion.classifier import classify_document
from app.config.loader import (
    load_client_config,
    list_available_tenants,
    TenantNotFoundError,
    InvalidClientConfigError,
)
from app.extraction.retriever import VectorStore
from app.extraction.extractor import build_claim_document
from app.review.queue import (
    add_to_review,
    get_review_item,
    list_pending_reviews,
    apply_correction,
    approve_as_is,
    get_queue_stats,
    CorrectionEntry,
)
from app.review.feedback import (
    export_correction_to_golden,
    list_feedback_entries,
    get_feedback_stats,
)
from app.metrics import INGEST_TOTAL, INGEST_DURATION, REVIEW_QUEUE_DEPTH, EXTRACTION_CONFIDENCE

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.10.0",
)

# Day 11: register global error handler
from app.errors import register_error_handlers
register_error_handlers(app)

# Day 13: Prometheus /metrics endpoint
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

# Single shared in-process vector store. Fine for dev/single-instance
# deployment; a multi-instance production deployment would point this at
# a persistent/shared Chroma instance instead of an in-memory one - noted
# here rather than silently assumed to already be production-ready.
vector_store = VectorStore()


class SearchRequest(BaseModel):
    tenant_id: str
    query: str
    top_k: int = 3


@app.get("/health")
def health() -> dict:
    """Liveness check. Docker/orchestrators hit this to confirm the service is up."""
    return {"status": "ok", "service": "claimsight", "version": "0.7.0"}


@app.get("/schema/claim-document")
def claim_document_schema() -> dict:
    """Expose the current ClaimDocument JSON schema."""
    return ClaimDocument.model_json_schema()


@app.get("/tenants")
def tenants() -> dict:
    """List configured tenants - useful for a client integration team to confirm their tenant_id is set up."""
    return {"tenants": list_available_tenants()}


@app.get("/tenants/{tenant_id}")
def tenant_config(tenant_id: str) -> dict:
    """Inspect one tenant's configuration."""
    try:
        config = load_client_config(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidClientConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config.model_dump()


@app.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    tenant_id: str = Form(..., description="Which tenant's config to apply"),
) -> dict:
    """
    Upload a claim document for a specific tenant: extract text, classify
    it, check it against the tenant's accepted document types, AND (new
    as of Day 6) chunk + embed + index it so it's searchable afterward
    via /search.
    """
    start_time = time.time()

    try:
        config = load_client_config(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidClientConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        contents = await file.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        extraction = extract_text(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    classification = classify_document(extraction.text)
    in_scope = classification.document_type in config.accepted_document_types

    document_id = str(uuid.uuid4())
    chunks_indexed = vector_store.index_document(document_id, tenant_id, extraction.text)

    # Structured extraction only runs for documents this tenant is
    # actually configured to accept. Extracting fields from an
    # out-of-scope document (e.g. a medical bill for a tenant whose
    # contract doesn't cover medical claims) would produce a fully-formed
    # ClaimDocument for something nobody agreed to process - the same
    # silent-wrong-behavior risk flagged in Day 4's docstring, one layer
    # deeper.
    extracted_document = None
    requires_review = None
    confidence_flags = None
    queued_for_review = False
    if in_scope and classification.document_type != DocumentType.UNKNOWN:
        extracted_document, confidence_report = build_claim_document(
            document_id, tenant_id, classification.document_type, extraction.text
        )
        requires_review = extracted_document.overall_confidence < config.review_threshold
        confidence_flags = confidence_report.flags if confidence_report.flags else None

        # Day 9: auto-route to human review queue if confidence is below threshold
        if requires_review:
            add_to_review(
                document_id=document_id,
                tenant_id=tenant_id,
                extracted_document=extracted_document,
                confidence_flags=confidence_flags or [],
            )
            queued_for_review = True

    # Day 13: record metrics
    duration = time.time() - start_time
    INGEST_TOTAL.labels(tenant_id=tenant_id, document_type=classification.document_type.value).inc()
    INGEST_DURATION.labels(extraction_method=extraction.method).observe(duration)
    if extracted_document and extracted_document.overall_confidence is not None:
        EXTRACTION_CONFIDENCE.labels(tenant_id=tenant_id).observe(extracted_document.overall_confidence)
    if queued_for_review:
        REVIEW_QUEUE_DEPTH.labels(tenant_id=tenant_id).inc()

    return {
        "document_id": document_id,
        "filename": file.filename,
        "tenant_id": tenant_id,
        "tenant_display_name": config.display_name,
        "extraction_method": extraction.method,
        "page_count": extraction.page_count,
        "pages_requiring_ocr": extraction.pages_ocr_count,
        "char_count": len(extraction.text),
        "document_type": classification.document_type.value,
        "classification_confidence": classification.confidence,
        "classification_scores": classification.scores,
        "in_scope_for_tenant": in_scope,
        "tenant_review_threshold": config.review_threshold,
        "chunks_indexed": chunks_indexed,
        "extracted_fields": extracted_document.model_dump(mode="json") if extracted_document else None,
        "requires_review": requires_review,
        "queued_for_review": queued_for_review,
        "confidence_flags": confidence_flags,
        "text_preview": extraction.text[:500],
        "full_text": extraction.text,
    }


@app.post("/search")
def search_documents(request: SearchRequest) -> dict:
    """
    Search previously-ingested documents for a tenant. Results are
    hard-filtered to `tenant_id` at the vector store level - not just
    "usually scoped by convention" - so this endpoint cannot return
    another tenant's content even if asked to.
    """
    try:
        load_client_config(request.tenant_id)  # validates tenant exists before searching
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidClientConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    results = vector_store.search(request.query, tenant_id=request.tenant_id, top_k=request.top_k)
    return {
        "query": request.query,
        "tenant_id": request.tenant_id,
        "results": [
            {
                "document_id": r.document_id,
                "chunk_index": r.chunk_index,
                "score": r.score,
                "text": r.text,
            }
            for r in results
        ],
    }


# --- Review queue endpoints ---

class CorrectionRequest(BaseModel):
    corrections: list[CorrectionEntry]


@app.get("/review/{tenant_id}")
def get_pending_reviews(tenant_id: str) -> dict:
    """
    List pending review items for a tenant. An adjuster's entry point:
    "show me what needs my attention." Scoped by tenant_id — an Acme
    adjuster never sees Beta's queue.
    """
    try:
        load_client_config(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidClientConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    items = list_pending_reviews(tenant_id)
    return {
        "tenant_id": tenant_id,
        "pending_count": len(items),
        "items": [item.model_dump(mode="json") for item in items],
    }


@app.get("/review/{tenant_id}/stats")
def review_queue_stats(tenant_id: str) -> dict:
    """Queue stats for monitoring / dashboards."""
    try:
        load_client_config(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidClientConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return get_queue_stats(tenant_id)


@app.get("/review/{tenant_id}/{document_id}")
def get_review_detail(tenant_id: str, document_id: str) -> dict:
    """Get the full detail of a single review item, including any corrections already applied."""
    item = get_review_item(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")
    if item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")
    return item.model_dump(mode="json")


@app.post("/review/{tenant_id}/{document_id}/correct")
def submit_correction(tenant_id: str, document_id: str, request: CorrectionRequest) -> dict:
    """
    Submit adjuster corrections for a review item. Corrections are
    APPENDED to the item, not overwriting the original extraction.
    Day 10: also auto-exports the corrected item as a new golden
    dataset entry, so the eval harness picks up real-world corrections
    alongside synthetic examples.
    """
    item = get_review_item(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")
    if item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")

    updated = apply_correction(document_id, request.corrections)

    # Day 10: auto-export correction to golden dataset
    feedback_path = export_correction_to_golden(updated)

    return {
        "document_id": document_id,
        "status": updated.status.value,
        "corrections_count": len(updated.corrections),
        "feedback_exported": feedback_path is not None,
    }


@app.post("/review/{tenant_id}/{document_id}/approve")
def approve_extraction(tenant_id: str, document_id: str) -> dict:
    """Adjuster reviewed it and the extraction is correct as-is."""
    item = get_review_item(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")
    if item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"No review item found for document '{document_id}'")

    updated = approve_as_is(document_id)
    return {
        "document_id": document_id,
        "status": updated.status.value,
    }


# --- Feedback endpoints ---

@app.get("/feedback")
def feedback_overview() -> dict:
    """Stats on how many adjuster corrections have been captured as golden dataset entries."""
    return get_feedback_stats()


@app.get("/feedback/entries")
def feedback_entries() -> dict:
    """List all feedback-sourced golden dataset entries."""
    entries = list_feedback_entries()
    return {"count": len(entries), "entries": entries}


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/health", "/schema/claim-document", "/tenants", "/tenants/{tenant_id}",
            "/ingest", "/search",
            "/review/{tenant_id}", "/review/{tenant_id}/stats",
            "/review/{tenant_id}/{document_id}",
            "/review/{tenant_id}/{document_id}/correct",
            "/review/{tenant_id}/{document_id}/approve",
            "/feedback", "/feedback/entries",
        ],
    }




