"""
Day 1 tests: prove the service starts and the schema is well-formed.
These are intentionally trivial - they exist so that from commit #1 onward,
`pytest` is a real gate, not something bolted on in Week 3. Every day after
this should add to this file, not create it for the first time later.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "docs" in response.json()


def test_claim_document_schema_is_well_formed():
    response = client.get("/schema/claim-document")
    assert response.status_code == 200
    schema = response.json()
    assert schema["title"] == "ClaimDocument"
    assert "document_id" in schema["properties"]
    assert "tenant_id" in schema["properties"]
