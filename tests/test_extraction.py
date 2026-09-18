"""
Day 7 tests: structured field extraction + its wiring into /ingest.

The three tests that matter most: extraction generalizing across
phrasing variants (not just the "normal" template), out-of-scope
documents correctly skipping extraction entirely, and the
requires_review routing decision actually firing off the tenant's real
configured threshold - not a hardcoded value.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import DocumentType
from app.extraction.extractor import RuleBasedExtractor, build_claim_document
from app.ingestion.ocr import extract_text

client = TestClient(app)


def test_extracts_claimant_name_and_policy_number_from_accident_report():
    text = "ACCIDENT REPORT\nClaimant Name: Jane Doe\nPolicy Number: XYZ-999\nIncident Date: 01/01/2026"
    fields, confidences = RuleBasedExtractor().extract(text, DocumentType.ACCIDENT_REPORT)
    assert fields["claimant_name"] == "Jane Doe"
    assert fields["policy_number"] == "XYZ-999"
    assert fields["incident_date"] == "01/01/2026"
    # All three fields present in the text -> all three should match
    assert all(fc.score == 0.95 for fc in confidences)


def test_extraction_generalizes_to_phrasing_variants():
    """The same test Day 5 ran on the classifier, one layer deeper: alternate real-world phrasing must still extract correctly."""
    text = "COLLISION INCIDENT SUMMARY\nDriver Involved: John Smith\nReference Number: REF-123"
    fields, _ = RuleBasedExtractor().extract(text, DocumentType.ACCIDENT_REPORT)
    assert fields["claimant_name"] == "John Smith"
    assert fields["policy_number"] == "REF-123"


def test_missing_field_gets_zero_confidence_not_omitted_silently():
    text = "ACCIDENT REPORT\nClaimant Name: Jane Doe"  # no policy number present
    fields, confidences = RuleBasedExtractor().extract(text, DocumentType.ACCIDENT_REPORT)
    assert "policy_number" not in fields
    policy_conf = next(fc for fc in confidences if fc.field_name == "policy_number")
    assert policy_conf.score == 0.0


def test_build_claim_document_against_real_golden_examples():
    """Run extraction through OCR-extracted text from real PDFs, not hand-typed strings."""
    extraction = extract_text("eval/golden_dataset/documents/claim_002_accident_phrasing_variant.pdf")
    doc, report = build_claim_document("test-id", "acme_insurance", DocumentType.ACCIDENT_REPORT, extraction.text)
    assert doc.claimant.full_name == "Priya Nair"
    assert doc.claimant.policy_number == "ACM-9982211"
    assert doc.overall_confidence > 0.8


def test_ingest_extracts_fields_when_in_scope():
    with open("data/sample_docs/accident_report_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("accident_report_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    body = response.json()
    assert body["extracted_fields"] is not None
    assert body["extracted_fields"]["claimant"]["full_name"] == "Maria Gonzalez"


def test_ingest_skips_extraction_when_out_of_scope():
    """Beta's config doesn't accept medical bills - extraction must not run at all, not run and get discarded."""
    with open("data/sample_docs/medical_bill_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("medical_bill_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "beta_insurance"},
        )
    body = response.json()
    assert body["in_scope_for_tenant"] is False
    assert body["extracted_fields"] is None
    assert body["requires_review"] is None


def test_requires_review_uses_the_tenant_actual_configured_threshold():
    """
    Acme's threshold is 0.85 (Day 4). RuleBasedExtractor's match
    confidence is 0.95, so a fully-matched document should NOT require
    review. This is the review_threshold field (defined Day 4, unused
    until today) actually being read and acted on.
    """
    with open("data/sample_docs/accident_report_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("accident_report_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    body = response.json()
    assert body["extracted_fields"]["overall_confidence"] >= 0.85
    assert body["requires_review"] is False
