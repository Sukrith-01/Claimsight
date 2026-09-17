"""
ClaimSight API entrypoint.

Day 1: health check + schema introspection.
Day 2: document ingestion (/ingest) with OCR.
Day 3: document classification wired into /ingest.
Day 4: per-tenant client config. /ingest now requires a tenant_id and
checks the classified document type against THAT tenant's accepted
types - this is the actual multi-tenant mechanism: one endpoint, N
tenants, each configured via YAML rather than a code branch.
"""

import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException

from app.models.schemas import ClaimDocument
from app.ingestion.ocr import extract_text
from app.ingestion.classifier import classify_document
from app.config.loader import (
    load_client_config,
    list_available_tenants,
    TenantNotFoundError,
    InvalidClientConfigError,
)

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.4.0",
)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


@app.get("/health")
def health() -> dict:
    """Liveness check. Docker/orchestrators hit this to confirm the service is up."""
    return {"status": "ok", "service": "claimsight", "version": "0.4.0"}


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
    """
    Inspect one tenant's configuration. Real-world use: a solutions
    engineer or client integration team hitting this to confirm the
    config they wrote actually loaded and validated the way they intended,
    without needing to read YAML or Python source.
    """
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
    Upload a claim document for a SPECIFIC tenant. Extraction and
    classification are the same for everyone; what's tenant-specific is
    whether the classified document type is one this tenant is configured
    to accept, and what review threshold applies to it.

    A document classified as a type the tenant hasn't configured for
    (e.g. a medical bill for a tenant whose contract doesn't cover
    medical claims) comes back flagged `in_scope_for_tenant: false`
    rather than being silently processed as if it were expected - wrong
    silent behavior here is exactly the kind of bug that's invisible
    until a client asks "why did you process something we never agreed
    you'd handle."
    """
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

    return {
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
        "text_preview": extraction.text[:500],
        "full_text": extraction.text,
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/health", "/schema/claim-document", "/tenants", "/tenants/{tenant_id}", "/ingest"],
    }



