"""
ClaimSight API entrypoint.

Day 1: health check + schema introspection.
Day 2: document ingestion (/ingest) - upload a PDF or image, get back
extracted text plus which extraction method was used. No structured
extraction yet - that's Week 2, once there's an extraction layer that
consumes this raw text and maps it onto ClaimDocument.
"""

import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException

from app.models.schemas import ClaimDocument
from app.ingestion.ocr import extract_text

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.2.0",
)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


@app.get("/health")
def health() -> dict:
    """Liveness check. Docker/orchestrators hit this to confirm the service is up."""
    return {"status": "ok", "service": "claimsight", "version": "0.2.0"}


@app.get("/schema/claim-document")
def claim_document_schema() -> dict:
    """Expose the current ClaimDocument JSON schema."""
    return ClaimDocument.model_json_schema()


@app.post("/ingest")
async def ingest_document(file: UploadFile = File(...)) -> dict:
    """
    Upload a claim document (PDF or image) and get back the raw extracted
    text, plus which extraction method was used (native text layer vs.
    OCR fallback) and how many pages needed OCR.

    This is intentionally the FULL response shape for now, not hidden
    behind a black box - in a client-facing system, showing which
    documents needed OCR (slower, occasionally noisier) vs. native
    extraction (fast, exact) is diagnostic information worth surfacing,
    not an implementation detail to bury.
    """
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
        result = extract_text(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "filename": file.filename,
        "extraction_method": result.method,
        "page_count": result.page_count,
        "pages_requiring_ocr": result.pages_ocr_count,
        "char_count": len(result.text),
        "text_preview": result.text[:500],
        "full_text": result.text,
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/health", "/schema/claim-document", "/ingest"],
    }

