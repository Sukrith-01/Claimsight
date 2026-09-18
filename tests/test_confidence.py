"""
Day 8 tests: confidence scoring - format plausibility, coverage penalties,
and human-readable flag generation.

The key thing these test beyond "does it produce a number" is that
confidence scoring DIFFERENTIATES meaningfully between scenarios Day 7's
binary model could not: a complete-but-suspicious extraction (name
contains digits from OCR noise) scores differently from a
clean-but-incomplete extraction (missing fields), which scores
differently from a perfect one. That graduated signal is the whole
point - it's what drives a useful requires_review decision instead of
a meaningless one.
"""

from app.extraction.confidence import score_extraction
from app.models.schemas import DocumentType


def test_perfect_extraction_gets_full_confidence():
    report = score_extraction(
        {"claimant_name": "Maria Gonzalez", "policy_number": "ACM-4471829", "incident_date": "08/22/2026"},
        DocumentType.ACCIDENT_REPORT,
    )
    assert report.overall_confidence == 1.0
    assert report.flags == []


def test_missing_field_drops_overall_below_threshold():
    """Missing one of three fields should push overall below Acme's 0.85 threshold."""
    report = score_extraction(
        {"claimant_name": "Maria Gonzalez", "policy_number": "ACM-4471829"},
        DocumentType.ACCIDENT_REPORT,
    )
    assert report.overall_confidence < 0.85
    assert any("incident_date" in f for f in report.flags)


def test_all_fields_missing_gives_zero():
    report = score_extraction({}, DocumentType.ACCIDENT_REPORT)
    assert report.overall_confidence == 0.0
    assert len(report.flags) == 3  # one flag per missing field


def test_name_with_digits_gets_low_score_and_flag():
    """OCR noise turning letters into digits is a real failure mode, not a hypothetical one."""
    report = score_extraction(
        {"claimant_name": "M4r1a G0nz4lez", "policy_number": "ACM-123", "incident_date": "08/22/2026"},
        DocumentType.ACCIDENT_REPORT,
    )
    name_conf = next(fc for fc in report.field_confidences if fc.field_name == "claimant_name")
    assert name_conf.score < 0.5
    assert any("digits" in f.lower() for f in report.flags)


def test_single_word_name_gets_moderate_score():
    report = score_extraction(
        {"claimant_name": "Maria", "policy_number": "ACM-123", "incident_date": "08/22/2026"},
        DocumentType.ACCIDENT_REPORT,
    )
    name_conf = next(fc for fc in report.field_confidences if fc.field_name == "claimant_name")
    assert 0.5 <= name_conf.score <= 0.7
    assert any("single word" in f.lower() for f in report.flags)


def test_date_that_looks_like_a_date_scores_high():
    report = score_extraction(
        {"claimant_name": "Jane Doe", "policy_number": "X-1", "incident_date": "03/14/2026"},
        DocumentType.ACCIDENT_REPORT,
    )
    date_conf = next(fc for fc in report.field_confidences if fc.field_name == "incident_date")
    assert date_conf.score >= 0.9


def test_date_that_doesnt_look_like_a_date_scores_low():
    report = score_extraction(
        {"claimant_name": "Jane Doe", "policy_number": "X-1", "incident_date": "Tuesday last week"},
        DocumentType.ACCIDENT_REPORT,
    )
    date_conf = next(fc for fc in report.field_confidences if fc.field_name == "incident_date")
    assert date_conf.score < 0.5


def test_currency_format_validation():
    good = score_extraction({"patient_name": "Jane Doe", "total_billed": "$1,735.00"}, DocumentType.MEDICAL_BILL)
    bad = score_extraction({"patient_name": "Jane Doe", "total_billed": "lots of money"}, DocumentType.MEDICAL_BILL)

    good_conf = next(fc for fc in good.field_confidences if fc.field_name == "total_billed")
    bad_conf = next(fc for fc in bad.field_confidences if fc.field_name == "total_billed")

    assert good_conf.score > bad_conf.score


def test_overall_confidence_penalizes_low_coverage():
    """
    A document with 1 of 3 fields perfectly extracted shouldn't get a
    high overall score just because that one field looks great - the 2
    missing fields matter.
    """
    one_of_three = score_extraction(
        {"claimant_name": "Jane Doe"},
        DocumentType.ACCIDENT_REPORT,
    )
    three_of_three = score_extraction(
        {"claimant_name": "Jane Doe", "policy_number": "ACM-123", "incident_date": "01/01/2026"},
        DocumentType.ACCIDENT_REPORT,
    )
    assert three_of_three.overall_confidence > one_of_three.overall_confidence


def test_flags_are_human_readable():
    """Flags exist to be shown to an adjuster, not logged and forgotten."""
    report = score_extraction(
        {"claimant_name": "X"},  # suspiciously short name
        DocumentType.ACCIDENT_REPORT,
    )
    assert len(report.flags) > 0
    assert all(isinstance(f, str) and len(f) > 10 for f in report.flags)


def test_ingest_surfaces_confidence_flags_in_response():
    """The /ingest endpoint should expose flags so a client can surface them to an adjuster."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    with open("eval/golden_dataset/documents/claim_003_accident_minimal.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("claim_003_accident_minimal.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    body = response.json()
    assert body["requires_review"] is True
    assert body["confidence_flags"] is not None
    assert len(body["confidence_flags"]) > 0
