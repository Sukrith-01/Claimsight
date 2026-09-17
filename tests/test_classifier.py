"""
Day 3 tests: document classifier + its wiring into /ingest.
"""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import DocumentType
from app.ingestion.classifier import classify_document

client = TestClient(app)

SAMPLE_DIR = "data/sample_docs"


@pytest.fixture(scope="module", autouse=True)
def ensure_sample_docs():
    if not os.path.exists(f"{SAMPLE_DIR}/medical_bill_sample.pdf"):
        subprocess.run([sys.executable, "scripts/generate_sample_docs.py"], check=True)


def test_classifies_accident_report():
    text = "ACCIDENT REPORT\nIncident Date: 08/22/2026\nReporting Officer: Badge #2214"
    result = classify_document(text)
    assert result.document_type == DocumentType.ACCIDENT_REPORT
    assert result.confidence > 0.5


def test_classifies_policy_document():
    text = "AUTO INSURANCE POLICY SUMMARY\nCoverage Period: 01/01/2026\nDeductible: $500"
    result = classify_document(text)
    assert result.document_type == DocumentType.POLICY_DOCUMENT


def test_classifies_medical_bill():
    text = "MEDICAL BILLING STATEMENT\nTotal Billed: $1,735.00\nDate of Service: 08/23/2026"
    result = classify_document(text)
    assert result.document_type == DocumentType.MEDICAL_BILL


def test_unrelated_text_returns_unknown_not_a_wrong_guess():
    """
    The important negative case: garbage/unrelated text must come back
    UNKNOWN, not a low-confidence wrong label. A classifier that always
    picks *something* is more dangerous than one that admits it isn't sure.
    """
    result = classify_document("Lorem ipsum dolor sit amet, nothing claim-related here at all.")
    assert result.document_type == DocumentType.UNKNOWN
    assert result.confidence == 0.0


def test_empty_text_returns_unknown():
    result = classify_document("")
    assert result.document_type == DocumentType.UNKNOWN


@pytest.mark.parametrize(
    "filename,expected_type",
    [
        ("accident_report_sample.pdf", "accident_report"),
        ("accident_report_scanned.pdf", "accident_report"),  # OCR path must classify correctly too
        ("policy_document_sample.pdf", "policy_document"),
        ("medical_bill_sample.pdf", "medical_bill"),
    ],
)
def test_ingest_endpoint_classifies_real_samples_correctly(filename, expected_type):
    with open(f"{SAMPLE_DIR}/{filename}", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": (filename, f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["document_type"] == expected_type
    assert body["classification_confidence"] > 0.5
