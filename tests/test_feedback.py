"""
Day 10 tests: feedback loop - corrections becoming golden dataset entries.

The tests that matter most: the exported label uses the same JSON shape
as hand-authored golden labels (so run_eval.py can consume both without
special handling), the diff between original and corrected is captured
(that's the actual training signal), and the auto-export fires when a
correction comes through the API endpoint.
"""

import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import DocumentType
from app.extraction.extractor import build_claim_document
from app.ingestion.ocr import extract_text
from app.review.queue import (
    add_to_review,
    apply_correction,
    clear_queue,
    CorrectionEntry,
    get_review_item,
)
from app.review.feedback import (
    export_correction_to_golden,
    list_feedback_entries,
    get_feedback_stats,
    FEEDBACK_DIR,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    clear_queue()
    if FEEDBACK_DIR.exists():
        shutil.rmtree(FEEDBACK_DIR)
    yield
    clear_queue()
    if FEEDBACK_DIR.exists():
        shutil.rmtree(FEEDBACK_DIR)


def _make_corrected_item(doc_id="fb-doc-1"):
    ext = extract_text("eval/golden_dataset/documents/claim_003_accident_minimal.pdf")
    doc, report = build_claim_document(doc_id, "acme_insurance", DocumentType.ACCIDENT_REPORT, ext.text)
    add_to_review(doc_id, "acme_insurance", doc, report.flags)
    apply_correction(doc_id, [
        CorrectionEntry(field_name="policy_number", original_value=None, corrected_value="FIXED-001"),
    ])
    return get_review_item(doc_id)


def test_export_creates_file():
    item = _make_corrected_item()
    path = export_correction_to_golden(item)
    assert path is not None
    assert path.exists()


def test_exported_label_matches_golden_format():
    """Must use the same JSON shape as hand-authored labels so run_eval.py works on both."""
    item = _make_corrected_item()
    path = export_correction_to_golden(item)

    with open(path) as f:
        label = json.load(f)

    # Same required keys as eval/golden_dataset/labels/*.json
    assert "example_id" in label
    assert "document_type" in label
    assert "expected_fields" in label
    assert isinstance(label["expected_fields"], dict)


def test_corrected_value_appears_in_expected_fields():
    item = _make_corrected_item()
    path = export_correction_to_golden(item)

    with open(path) as f:
        label = json.load(f)

    assert label["expected_fields"]["policy_number"] == "FIXED-001"


def test_diff_between_original_and_corrected_is_captured():
    """The diff IS the training signal — not just what the final answer is, but what the system got wrong."""
    item = _make_corrected_item()
    path = export_correction_to_golden(item)

    with open(path) as f:
        label = json.load(f)

    assert "corrections_applied" in label
    assert len(label["corrections_applied"]) == 1
    c = label["corrections_applied"][0]
    assert c["field_name"] == "policy_number"
    assert c["original_value"] is None
    assert c["corrected_value"] == "FIXED-001"


def test_non_corrected_item_returns_none():
    ext = extract_text("eval/golden_dataset/documents/claim_003_accident_minimal.pdf")
    doc, report = build_claim_document("uncorrected", "acme_insurance", DocumentType.ACCIDENT_REPORT, ext.text)
    add_to_review("uncorrected", "acme_insurance", doc, report.flags)
    item = get_review_item("uncorrected")

    path = export_correction_to_golden(item)
    assert path is None


def test_feedback_stats():
    _make_corrected_item("doc-a")
    export_correction_to_golden(get_review_item("doc-a"))

    stats = get_feedback_stats()
    assert stats["total_feedback_entries"] == 1
    assert stats["by_tenant"]["acme_insurance"] == 1


def test_correction_via_api_auto_exports_feedback():
    """The full loop through the API: correction -> feedback entry created automatically."""
    ext = extract_text("eval/golden_dataset/documents/claim_003_accident_minimal.pdf")
    doc, report = build_claim_document("api-fb-doc", "acme_insurance", DocumentType.ACCIDENT_REPORT, ext.text)
    add_to_review("api-fb-doc", "acme_insurance", doc, report.flags)

    response = client.post(
        "/review/acme_insurance/api-fb-doc/correct",
        json={"corrections": [{"field_name": "policy_number", "corrected_value": "API-FIX"}]},
    )
    assert response.status_code == 200
    assert response.json()["feedback_exported"] is True

    entries = list_feedback_entries()
    assert len(entries) == 1
    assert entries[0]["expected_fields"]["policy_number"] == "API-FIX"


def test_feedback_api_endpoints():
    _make_corrected_item("stats-doc")
    export_correction_to_golden(get_review_item("stats-doc"))

    stats_response = client.get("/feedback")
    assert stats_response.status_code == 200
    assert stats_response.json()["total_feedback_entries"] == 1

    entries_response = client.get("/feedback/entries")
    assert entries_response.status_code == 200
    assert entries_response.json()["count"] == 1
