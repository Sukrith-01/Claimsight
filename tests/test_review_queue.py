"""
Day 9 tests: human review queue.

The tests that matter most: corrections APPEND (don't overwrite),
ingest auto-routes low-confidence documents, and an adjuster for one
tenant never sees another tenant's queue.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import DocumentType
from app.extraction.extractor import build_claim_document
from app.review.queue import (
    add_to_review,
    get_review_item,
    list_pending_reviews,
    apply_correction,
    approve_as_is,
    get_queue_stats,
    clear_queue,
    CorrectionEntry,
    ReviewItemStatus,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_queue():
    """Every test starts with a fresh queue — no leftover state between tests."""
    clear_queue()
    yield
    clear_queue()


def _make_test_doc(doc_id="doc-1", tenant="acme_insurance"):
    """Helper: build a ClaimDocument from the minimal accident report (low confidence, triggers review)."""
    from app.ingestion.ocr import extract_text
    ext = extract_text("eval/golden_dataset/documents/claim_003_accident_minimal.pdf")
    doc, report = build_claim_document(doc_id, tenant, DocumentType.ACCIDENT_REPORT, ext.text)
    return doc, report


def test_add_and_retrieve_review_item():
    doc, report = _make_test_doc()
    add_to_review("doc-1", "acme_insurance", doc, report.flags)
    item = get_review_item("doc-1")
    assert item is not None
    assert item.status == ReviewItemStatus.PENDING
    assert len(item.confidence_flags) > 0


def test_list_pending_reviews_scoped_to_tenant():
    doc1, report1 = _make_test_doc("doc-a", "acme_insurance")
    doc2, report2 = _make_test_doc("doc-b", "beta_insurance")
    add_to_review("doc-a", "acme_insurance", doc1, report1.flags)
    add_to_review("doc-b", "beta_insurance", doc2, report2.flags)

    acme_pending = list_pending_reviews("acme_insurance")
    beta_pending = list_pending_reviews("beta_insurance")

    assert len(acme_pending) == 1
    assert acme_pending[0].document_id == "doc-a"
    assert len(beta_pending) == 1
    assert beta_pending[0].document_id == "doc-b"


def test_corrections_append_not_overwrite():
    """THE audit-trail test: original extraction must survive correction."""
    doc, report = _make_test_doc()
    add_to_review("doc-1", "acme_insurance", doc, report.flags)

    original_claimant = doc.claimant.full_name

    apply_correction("doc-1", [
        CorrectionEntry(field_name="policy_number", original_value=None, corrected_value="FIXED-001")
    ])

    item = get_review_item("doc-1")
    assert item.status == ReviewItemStatus.CORRECTED
    assert len(item.corrections) == 1
    assert item.corrections[0].corrected_value == "FIXED-001"
    # Original extraction is still intact
    assert item.extracted_document.claimant.full_name == original_claimant


def test_approve_as_is():
    doc, report = _make_test_doc()
    add_to_review("doc-1", "acme_insurance", doc, report.flags)

    item = approve_as_is("doc-1")
    assert item.status == ReviewItemStatus.APPROVED_AS_IS
    assert item.reviewed_at is not None
    assert len(item.corrections) == 0


def test_queue_stats():
    doc1, r1 = _make_test_doc("doc-1")
    doc2, r2 = _make_test_doc("doc-2")
    add_to_review("doc-1", "acme_insurance", doc1, r1.flags)
    add_to_review("doc-2", "acme_insurance", doc2, r2.flags)

    apply_correction("doc-1", [CorrectionEntry(field_name="x", corrected_value="y")])

    stats = get_queue_stats("acme_insurance")
    assert stats["total"] == 2
    assert stats["pending"] == 1
    assert stats["corrected"] == 1


# --- API endpoint tests ---

def test_ingest_auto_routes_low_confidence_to_review():
    """The full loop: ingest a low-confidence document, then verify it appears in the review queue."""
    with open("eval/golden_dataset/documents/claim_003_accident_minimal.pdf", "rb") as f:
        ingest_response = client.post(
            "/ingest",
            files={"file": ("claim_003_accident_minimal.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    body = ingest_response.json()
    assert body["requires_review"] is True
    assert body["queued_for_review"] is True

    queue_response = client.get("/review/acme_insurance")
    queue_body = queue_response.json()
    assert queue_body["pending_count"] >= 1


def test_review_endpoint_rejects_unknown_tenant():
    response = client.get("/review/fake_tenant")
    assert response.status_code == 404


def test_correction_via_api():
    doc, report = _make_test_doc()
    add_to_review("api-doc-1", "acme_insurance", doc, report.flags)

    response = client.post(
        "/review/acme_insurance/api-doc-1/correct",
        json={"corrections": [{"field_name": "policy_number", "corrected_value": "API-FIX-001"}]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "corrected"


def test_approve_via_api():
    doc, report = _make_test_doc()
    add_to_review("api-doc-2", "acme_insurance", doc, report.flags)

    response = client.post("/review/acme_insurance/api-doc-2/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved_as_is"


def test_review_detail_enforces_tenant_id():
    """An adjuster trying to access another tenant's review item gets a 404, not the item."""
    doc, report = _make_test_doc("doc-acme", "acme_insurance")
    add_to_review("doc-acme", "acme_insurance", doc, report.flags)

    response = client.get("/review/beta_insurance/doc-acme")
    assert response.status_code == 404
