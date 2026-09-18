"""
Confidence scoring: how sure are we that an extracted value is CORRECT,
not just that a pattern matched?

Why this is its own module rather than a few more lines inside
extractor.py: confidence and extraction are different questions. The
extractor's job is "what value did the text contain for this field?"
The confidence scorer's job is "how much should we trust that value?"
Mixing them means you can't change one without risking the other, and
more practically, you can't test confidence logic in isolation -
you'd always need a full extraction pipeline running just to ask "would
this field value look trustworthy?"

Day 7's extractor assigned 0.95 for any regex match and 0.0 for any
miss. That's a placeholder this module replaces. The signals here are
deliberately simple and interpretable - no ML model, no black box -
because the whole point of confidence in a human-in-the-loop system is
that an adjuster should be able to look at a flagged extraction and
understand WHY it was flagged, not just that it was.

Signals used:
  1. Field completeness: did the extraction produce a value at all?
  2. Format plausibility: does the value look like what this field type
     should contain? (e.g. a date field that doesn't parse as a date,
     a dollar amount with letters in it, a name that's suspiciously
     short or long)
  3. Extraction coverage: what fraction of expected fields for this
     document type actually matched? A document missing 2 of 3 fields
     is less trustworthy overall than one missing 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.schemas import DocumentType, FieldConfidence


@dataclass
class ConfidenceReport:
    field_confidences: list[FieldConfidence]
    overall_confidence: float
    flags: list[str]  # human-readable reasons for low confidence, surfaced to the adjuster


# --- per-field format validators ---
# Each returns a score between 0.0 and 1.0 representing how plausible
# the extracted value looks for that field type. These are heuristics,
# not parsers - they're meant to catch obvious noise (OCR garbage, a
# truncated value), not validate that a date is a real calendar date or
# a policy number exists in a database.

def _score_name(value: str) -> tuple[float, str | None]:
    """Is this plausible as a person's name?"""
    if not value or len(value) < 2:
        return 0.2, "Name is suspiciously short"
    if len(value) > 80:
        return 0.3, "Name is suspiciously long (possible OCR run-on)"
    if re.search(r"\d", value):
        return 0.4, "Name contains digits"
    if not re.search(r"[a-zA-Z]", value):
        return 0.2, "Name contains no alphabetic characters"
    parts = value.split()
    if len(parts) < 2:
        return 0.6, "Name appears to be a single word (missing first or last name?)"
    return 1.0, None


def _score_policy_number(value: str) -> tuple[float, str | None]:
    """Is this plausible as a policy/reference number?"""
    if not value or len(value) < 3:
        return 0.3, "Policy number is suspiciously short"
    if len(value) > 30:
        return 0.4, "Policy number is suspiciously long"
    # Most policy numbers are alphanumeric with dashes/dots
    if re.fullmatch(r"[A-Za-z0-9\-\.#/ ]+", value):
        return 1.0, None
    return 0.5, "Policy number contains unusual characters"


def _score_date(value: str) -> tuple[float, str | None]:
    """Does this look like a date string?"""
    if not value:
        return 0.0, "Date field is empty"
    # Common US date formats: MM/DD/YYYY, MM-DD-YYYY, Month DD, YYYY
    if re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", value):
        return 1.0, None
    if re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", value, re.IGNORECASE):
        return 0.9, None
    return 0.4, "Date field doesn't match common date formats"


def _score_currency(value: str) -> tuple[float, str | None]:
    """Does this look like a dollar amount?"""
    if not value:
        return 0.0, "Currency field is empty"
    cleaned = value.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\$?\d+\.?\d*", cleaned):
        return 1.0, None
    if "$" in value and re.search(r"\d", value):
        return 0.7, "Currency field has some numeric content but unusual formatting"
    return 0.3, "Currency field doesn't look like a dollar amount"


# Map field names to their format validators
_FIELD_VALIDATORS: dict[str, callable] = {
    "claimant_name": _score_name,
    "policyholder": _score_name,
    "patient_name": _score_name,
    "policy_number": _score_policy_number,
    "incident_date": _score_date,
    "total_billed": _score_currency,
}

# Expected fields per document type - used for coverage scoring
_EXPECTED_FIELDS: dict[DocumentType, list[str]] = {
    DocumentType.ACCIDENT_REPORT: ["claimant_name", "policy_number", "incident_date"],
    DocumentType.POLICY_DOCUMENT: ["policyholder", "policy_number"],
    DocumentType.MEDICAL_BILL: ["patient_name", "total_billed"],
}


def score_extraction(
    extracted_fields: dict[str, str],
    document_type: DocumentType,
) -> ConfidenceReport:
    """
    Score how trustworthy a set of extracted fields looks, using
    format plausibility + field coverage.

    Returns per-field confidences (each with a score from 0.0 to 1.0)
    plus an overall confidence and human-readable flags explaining any
    low scores - meant to be surfaced to an adjuster, not buried in logs.
    """
    expected = _EXPECTED_FIELDS.get(document_type, [])
    field_confidences: list[FieldConfidence] = []
    flags: list[str] = []

    for field_name in expected:
        value = extracted_fields.get(field_name)

        if value is None:
            # Field wasn't extracted at all - lowest confidence
            field_confidences.append(FieldConfidence(field_name=field_name, score=0.0))
            flags.append(f"'{field_name}' was not found in the document")
            continue

        # Run the format validator if one exists for this field type
        validator = _FIELD_VALIDATORS.get(field_name)
        if validator:
            format_score, flag = validator(value)
            field_confidences.append(FieldConfidence(field_name=field_name, score=round(format_score, 3)))
            if flag:
                flags.append(f"'{field_name}': {flag}")
        else:
            # No validator for this field - give it a moderate confidence
            # rather than max, since we have no way to check it
            field_confidences.append(FieldConfidence(field_name=field_name, score=0.8))

    # Coverage factor: what fraction of expected fields were actually found?
    # A document missing most of its expected fields is less trustworthy
    # overall, even if the ones that were found look fine individually.
    found_count = sum(1 for f in expected if f in extracted_fields)
    coverage = found_count / len(expected) if expected else 1.0

    # Overall confidence: mean of field scores, weighted down by coverage
    # if coverage is poor. A document with 1 of 3 fields perfectly
    # extracted (individual mean might be high) shouldn't get a high
    # overall score - it's mostly guessing.
    if field_confidences:
        mean_field_score = sum(fc.score for fc in field_confidences) / len(field_confidences)
        overall = round(mean_field_score * (0.5 + 0.5 * coverage), 3)
    else:
        overall = 0.0

    return ConfidenceReport(
        field_confidences=field_confidences,
        overall_confidence=overall,
        flags=flags,
    )
