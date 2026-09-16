"""
ClaimSight API entrypoint.

Day 1 scope, deliberately: health check + schema introspection only.
No extraction logic yet - that's Week 2. The point of Day 1 is a service
that starts, responds, and has a real data contract behind it, so every
day after this adds to something running rather than something imagined.
"""

from fastapi import FastAPI

from app.models.schemas import ClaimDocument

app = FastAPI(
    title="ClaimSight",
    description="Multi-tenant insurance claims document intelligence platform.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness check. Docker/orchestrators hit this to confirm the service is up."""
    return {"status": "ok", "service": "claimsight", "version": "0.1.0"}


@app.get("/schema/claim-document")
def claim_document_schema() -> dict:
    """
    Expose the current ClaimDocument JSON schema.

    Useful in practice for two reasons: (1) a client integration team can
    hit this to see exactly what shape they'll receive without reading
    source code, and (2) it's a cheap regression check - if this schema
    changes unexpectedly between commits, something downstream probably
    needs updating too.
    """
    return ClaimDocument.model_json_schema()


@app.get("/")
def root() -> dict:
    return {
        "service": "claimsight",
        "docs": "/docs",
        "health": "/health",
    }
