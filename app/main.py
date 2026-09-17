"""
ClaimSight API entrypoint.

Day 1: health check + schema introspection.
Day 2: document ingestion (/ingest) - upload a PDF or image, get back
extracted text plus which extraction method was used.
Day 3: document classification wired into /ingest - now also returns
which type of claim document this is (accident report / policy / medical
bill), with a confidence score. Structured field extraction is still
Week 2 - classification only tells us WHAT the document is, not what's
inside it yet.
"""

import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException

from app.models.schemas import ClaimDocument
from app.ingestion.ocr import extract_text
from app.ingestion.classifier import classify_document

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.3.0",
)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


@app.get("/health")
def health() -> dict:
    """Liveness check. Docker/orchestrators hit this to confirm the service is up."""
    return {"status": "ok", "service": "claimsight", "version": "0.3.0"}


@app.get("/schema/claim-document")
def claim_document_schema() -> dict:
    """Expose the current ClaimDocument JSON schema."""
    return ClaimDocument.model_json_schema()


@app.post("/ingest")
async def ingest_document(file: UploadFile = File(...)) -> dict:
    """
    Upload a claim document (PDF or image) and get back the raw extracted
    text, the extraction method used, AND (new as of Day 3) which type of
    claim document this is, with a classification confidence score.

    If classification confidence is low, `document_type` comes back as
    "unknown" rather than a guessed label - an honest "not sure" is more
    useful downstream than a wrong confident answer, because Week 2's
    extraction layer will pick which schema to apply based on this field.
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
        extraction = extract_text(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    classification = classify_document(extraction.text)

    return {
        "filename": file.filename,
        "extraction_method": extraction.method,
        "page_count": extraction.page_count,
        "pages_requiring_ocr": extraction.pages_ocr_count,
        "char_count": len(extraction.text),
        "document_type": classification.document_type.value,
        "classification_confidence": classification.confidence,
        "classification_scores": classification.scores,
        "text_preview": extraction.text[:500],
        "full_text": extraction.text,
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/health", "/schema/claim-document", "/ingest"],
    }


