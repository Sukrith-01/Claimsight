"""
Day 2 tests: OCR extraction module + /ingest endpoint.

Uses the same generated sample docs a developer would use locally - if
scripts/generate_sample_docs.py hasn't been run, these tests generate
them fresh via a fixture rather than failing with a confusing FileNotFound.
"""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ingestion.ocr import extract_text

client = TestClient(app)

SAMPLE_DIR = "data/sample_docs"


@pytest.fixture(scope="module", autouse=True)
def ensure_sample_docs():
    """Generate sample docs once per test run if they don't already exist."""
    if not os.path.exists(f"{SAMPLE_DIR}/medical_bill_sample.pdf"):
        subprocess.run([sys.executable, "scripts/generate_sample_docs.py"], check=True)


def test_native_pdf_extraction():
    result = extract_text(f"{SAMPLE_DIR}/medical_bill_sample.pdf")
    assert result.method == "native"
    assert result.pages_ocr_count == 0
    assert "Maria Gonzalez" in result.text
    assert "Total Billed" in result.text


def test_scanned_pdf_falls_back_to_ocr():
    result = extract_text(f"{SAMPLE_DIR}/accident_report_scanned.pdf")
    assert result.method == "ocr"
    assert result.pages_ocr_count == 1
    # OCR isn't pixel-perfect, so check for a distinctive substring
    # rather than exact match.
    assert "Maria Gonzalez" in result.text
    assert "ACCIDENT REPORT" in result.text


def test_unsupported_extension_raises():
    with pytest.raises(ValueError):
        extract_text("some_file.docx")


def test_ingest_endpoint_native_pdf():
    with open(f"{SAMPLE_DIR}/policy_document_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("policy_document_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["extraction_method"] == "native"
    assert "Maria Gonzalez" in body["full_text"]


def test_ingest_endpoint_scanned_pdf():
    with open(f"{SAMPLE_DIR}/accident_report_scanned.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("accident_report_scanned.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["extraction_method"] == "ocr"
    assert body["pages_requiring_ocr"] == 1


def test_ingest_endpoint_rejects_unsupported_type():
    response = client.post(
        "/ingest",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
        data={"tenant_id": "acme_insurance"},
    )
    assert response.status_code == 400
