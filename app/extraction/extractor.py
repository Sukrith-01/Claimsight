"""
Turns raw extracted text into structured fields on a ClaimDocument.

SAME DESIGN PATTERN AS embeddings.py (Day 6) - read that module's
docstring first if you haven't. Short version: an `Extractor` protocol
with a free, deterministic, dependency-free implementation
(`RuleBasedExtractor`) as the active one for dev/CI, and an
`LLMExtractor` stub ready to activate once there's an API key and budget
for it - a config swap, not a rewrite.

Field extraction is a stronger case for an eventual LLM than embeddings
was, and worth being honest about: regex extraction is brittle against
phrasing it wasn't written for (Day 5's eval already proved this pattern
with the classifier - "COLLISION INCIDENT SUMMARY" wasn't in the
original keyword list). An LLM would generalize to phrasings never
explicitly coded for. RuleBasedExtractor exists so the pipeline (and its
eval harness) has something real to run end-to-end NOW, and so there's a
measured baseline to compare an LLM extractor against later - the same
reasoning as Day 3's classifier, applied one layer deeper.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.models.schemas import (
    ClaimDocument,
    Claimant,
    DocumentType,
    FieldConfidence,
)


class Extractor(Protocol):
    def extract(self, text: str, document_type: DocumentType) -> tuple[dict, list[FieldConfidence]]: ...


# Each field maps to a list of possible label patterns, because Day 5's
# eval already proved real documents use different wording for the same
# field ("Policy Number" vs "Reference Number" vs "Certificate Number").
# Patterns are tried in order; first match wins.
_FIELD_PATTERNS: dict[DocumentType, dict[str, list[str]]] = {
    DocumentType.ACCIDENT_REPORT: {
        "claimant_name": [
            r"Claimant Name:\s*(.+)",
            r"Driver Involved:\s*(.+)",
        ],
        "policy_number": [
            r"Policy Number:\s*(.+)",
            r"Reference Number:\s*(.+)",
        ],
        "incident_date": [
            r"Incident Date:\s*(.+)",
            r"Date of Occurrence:\s*(.+)",
        ],
    },
    DocumentType.POLICY_DOCUMENT: {
        "policyholder": [
            r"Policyholder:\s*(.+)",
            r"Insured Party:\s*(.+)",
        ],
        "policy_number": [
            r"Policy Number:\s*(.+)",
            r"Certificate Number:\s*(.+)",
        ],
    },
    DocumentType.MEDICAL_BILL: {
        "patient_name": [
            r"Patient Name:\s*(.+)",
            r"Patient:\s*(.+)",
        ],
        "total_billed": [
            r"Total Billed:\s*(.+)",
            r"Amount Due:\s*(.+)",
        ],
    },
}


class RuleBasedExtractor:
    """
    Regex-based field extraction. Deterministic and free, at the cost of
    only recognizing phrasings someone explicitly wrote a pattern for.

    Confidence model: a field either matched a pattern (confidence 0.95 -
    not 1.0, because even a successful regex match doesn't guarantee the
    captured text is semantically correct, e.g. OCR noise inside the
    match) or didn't (confidence 0.0, field omitted). This is intentionally
    binary and unsubtle compared to what a real ML-based confidence score
    would look like - documented as a known simplification, not something
    to mistake for sophistication it doesn't have.
    """

    MATCH_CONFIDENCE = 0.95

    def extract(self, text: str, document_type: DocumentType) -> tuple[dict, list[FieldConfidence]]:
        patterns = _FIELD_PATTERNS.get(document_type, {})
        fields: dict[str, str] = {}
        confidences: list[FieldConfidence] = []

        for field_name, pattern_list in patterns.items():
            matched_value = None
            for pattern in pattern_list:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    matched_value = match.group(1).strip()
                    # Stop at end of line - a greedy (.+) on a single-line
                    # regex already does this since `text` isn't
                    # multi-line-matched, but strip trailing whitespace/
                    # stray characters defensively.
                    matched_value = matched_value.splitlines()[0].strip()
                    break

            if matched_value:
                fields[field_name] = matched_value
                confidences.append(FieldConfidence(field_name=field_name, score=self.MATCH_CONFIDENCE))
            else:
                confidences.append(FieldConfidence(field_name=field_name, score=0.0))

        return fields, confidences


class LLMExtractor:
    """
    Stub for the production path - an LLM call constrained to the
    ClaimDocument schema (e.g. via function calling / structured output),
    which would generalize to phrasings RuleBasedExtractor was never
    explicitly written to handle. Activating this is a config change
    (swap which extractor main.py constructs) once there's an API key,
    not a rewrite of anything that calls it.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5"):
        raise NotImplementedError(
            "LLMExtractor is a stub for the production path. "
            "RuleBasedExtractor is the active extractor for local dev/CI - "
            "see the module docstring for why."
        )


def build_claim_document(
    document_id: str,
    tenant_id: str,
    document_type: DocumentType,
    text: str,
    extractor: Extractor | None = None,
) -> ClaimDocument:
    """
    Runs extraction and assembles a validated ClaimDocument. Overall
    confidence is the mean of field confidences - simple on purpose; a
    weighted or ML-based aggregate is future work once there's a reason
    (real eval data) to justify the added complexity over this baseline.
    """
    extractor = extractor or RuleBasedExtractor()
    fields, field_confidences = extractor.extract(text, document_type)

    claimant = None
    if "claimant_name" in fields or "policyholder" in fields or "patient_name" in fields:
        name = fields.get("claimant_name") or fields.get("policyholder") or fields.get("patient_name")
        claimant = Claimant(
            full_name=name,
            policy_number=fields.get("policy_number"),
        )

    overall_confidence = (
        sum(fc.score for fc in field_confidences) / len(field_confidences)
        if field_confidences
        else 0.0
    )

    return ClaimDocument(
        document_id=document_id,
        tenant_id=tenant_id,
        document_type=document_type,
        claimant=claimant,
        field_confidences=field_confidences,
        overall_confidence=round(overall_confidence, 3),
        raw_text_excerpt=text[:500],
    )
