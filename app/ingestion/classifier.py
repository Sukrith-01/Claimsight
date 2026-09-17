"""
Document classification: given raw extracted text, decide which kind of
claim document it is (accident report, policy document, medical bill).

Design decision (Day 3): this is a KEYWORD-SCORING classifier, not an LLM
call. That's deliberate, not a shortcut taken because it's easier:

  1. It's free and instant - no API key, no network call, no latency -
     which matters because classification runs on every single document
     before anything else happens to it.
  2. It's fully deterministic and testable without mocking an API.
  3. It gives us a real baseline to compare an LLM-based classifier
     against later, once eval infrastructure exists (Week 3). Swapping
     in an LLM classifier without ever having measured "how good is the
     dumb version" is how teams end up unable to tell whether the
     expensive version is actually earning its cost.

This will very likely get replaced or augmented by an LLM call in a
later week for documents that don't score clearly on keywords alone
(handwritten notes, unusual formats). That's a config-driven decision
for Week 2's extraction layer, not something to pre-build here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import DocumentType

# Keyword sets per document type. Weighted lists, not just presence/absence -
# some phrases are much stronger signals than others ("total billed" is a
# near-certain medical bill signal; "date" alone is not).
_KEYWORDS: dict[DocumentType, list[tuple[str, float]]] = {
    DocumentType.ACCIDENT_REPORT: [
        ("accident report", 3.0),
        ("incident date", 2.0),
        ("incident description", 2.0),
        ("reporting officer", 2.5),
        ("collision", 1.5),
        ("location", 0.5),
        ("report filed", 1.5),
    ],
    DocumentType.POLICY_DOCUMENT: [
        ("policy summary", 3.0),
        ("insurance policy", 2.5),
        ("coverage period", 2.5),
        ("liability coverage", 2.0),
        ("collision coverage", 2.0),
        ("comprehensive coverage", 2.0),
        ("deductible", 1.5),
        ("policyholder", 2.0),
        ("underwriting", 1.5),
    ],
    DocumentType.MEDICAL_BILL: [
        ("medical billing", 3.0),
        ("billing statement", 2.5),
        ("total billed", 2.5),
        ("line items", 1.0),
        ("date of service", 2.0),
        ("provider", 1.0),
        ("dx:", 1.5),
        ("diagnosis code", 2.0),
        ("patient name", 1.5),
    ],
}

# Minimum score to accept a classification at all. Below this, we'd
# rather honestly report UNKNOWN than guess - a wrong confident
# classification is worse than an honest "not sure," because it silently
# routes the document into the wrong extraction schema downstream.
MIN_SCORE_THRESHOLD = 2.0


@dataclass
class ClassificationResult:
    document_type: DocumentType
    confidence: float  # 0.0-1.0, normalized score of the winning type
    scores: dict[str, float]  # raw scores per type, for debugging/eval


def classify_document(text: str) -> ClassificationResult:
    """
    Score the text against each document type's keyword set and return
    the best match, or UNKNOWN if nothing scores above threshold.
    """
    text_lower = text.lower()

    raw_scores: dict[DocumentType, float] = {}
    for doc_type, keywords in _KEYWORDS.items():
        score = sum(weight for phrase, weight in keywords if phrase in text_lower)
        raw_scores[doc_type] = score

    best_type = max(raw_scores, key=raw_scores.get)
    best_score = raw_scores[best_type]

    if best_score < MIN_SCORE_THRESHOLD:
        return ClassificationResult(
            document_type=DocumentType.UNKNOWN,
            confidence=0.0,
            scores={k.value: v for k, v in raw_scores.items()},
        )

    # Normalize confidence: how dominant is the winner over the runner-up?
    # A document that scores 8.0 on accident_report and 0.5 on everything
    # else should read as high-confidence; one that scores 3.0 vs 2.8
    # should not, even though both "win."
    sorted_scores = sorted(raw_scores.values(), reverse=True)
    runner_up = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    margin = best_score - runner_up
    confidence = min(1.0, 0.5 + (margin / (best_score + 1e-6)) * 0.5)

    return ClassificationResult(
        document_type=best_type,
        confidence=round(confidence, 3),
        scores={k.value: v for k, v in raw_scores.items()},
    )
