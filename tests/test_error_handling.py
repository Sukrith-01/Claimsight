"""
Day 11 tests: error handling for realistic failure modes.

These test the unglamorous 80% of real deployment work: what happens
when a user uploads garbage, an empty file, or something that isn't
actually a PDF. The system should return a clear error, not crash.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.ingestion.ocr import extract_text
import pytest

client = TestClient(app)


def test_empty_file_upload_returns_400():
    response = client.post(
        "/ingest",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"tenant_id": "acme_insurance"},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_corrupted_pdf_returns_422():
    response = client.post(
        "/ingest",
        files={"file": ("corrupted.pdf", b"not a real pdf at all", "application/pdf")},
        data={"tenant_id": "acme_insurance"},
    )
    assert response.status_code == 422


def test_ocr_extract_raises_on_corrupted_file(tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"this is not a pdf")
    with pytest.raises(ValueError, match="Failed to open PDF"):
        extract_text(str(bad_pdf))


def test_missing_file_field_returns_422():
    response = client.post(
        "/ingest",
        data={"tenant_id": "acme_insurance"},
    )
    assert response.status_code == 422
