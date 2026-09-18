"""
ClaimSight API entrypoint.

Day 1: health check + schema introspection.
Day 2: document ingestion (/ingest) with OCR.
Day 3: document classification wired into /ingest.
Day 4: per-tenant client config.
Day 6: chunking + embeddings + vector search. /ingest now also indexes
the document for later retrieval, and a new /search endpoint queries
across a tenant's indexed documents - tenant-scoped, so one tenant's
search never surfaces another tenant's content.
"""

import tempfile
import uuid
from pathlib import Path

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

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.7.0",
)

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
    if in_scope and classification.document_type != DocumentType.UNKNOWN:
        extracted_document = build_claim_document(
            document_id, tenant_id, classification.document_type, extraction.text
        )
        requires_review = extracted_document.overall_confidence < config.review_threshold

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


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/health", "/schema/claim-document", "/tenants", "/tenants/{tenant_id}",
            "/ingest", "/search",
        ],
    }




