"""
Feedback loop: turns adjuster corrections into golden dataset entries.

This is the piece that makes the system LEARN from its mistakes rather
than just record them. When an adjuster corrects an extraction (Day 9),
the diff between what the system predicted and what the human said is
correct is exactly the kind of signal an eval harness needs: a real
document where we now know the right answer because a domain expert
told us.

Two modes of value here:

1. IMMEDIATE: every correction becomes a new golden dataset entry that
   the eval harness (Day 5 / eval/run_eval.py) can measure against on
   the next run. Accuracy numbers that include real-world corrections
   are more honest than ones based purely on synthetic data generated
   by the developer.

2. FUTURE: if/when the system moves from RuleBasedExtractor to
   LLMExtractor, these correction pairs (input document + corrected
   fields) are exactly the fine-tuning or few-shot examples that would
   improve the LLM's extraction quality. Building the feedback
   infrastructure now means that data is already accumulating by the
   time the LLM path is activated, instead of starting from zero.

Storage: JSON files in eval/golden_dataset/feedback/, one per
correction. Deliberately separate from the hand-authored golden
examples in eval/golden_dataset/labels/ so the two sources can be
tracked, weighted, and audited independently.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.review.queue import ReviewItem, ReviewItemStatus

FEEDBACK_DIR = Path("eval/golden_dataset/feedback")


def _ensure_feedback_dir() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def export_correction_to_golden(item: ReviewItem) -> Path | None:
    """
    Takes a corrected ReviewItem and writes a golden-dataset-format
    label file that merges the original extraction with the adjuster's
    corrections. Returns the path to the new file, or None if the item
    hasn't been corrected.

    The exported label uses the same JSON shape as the hand-authored
    labels in eval/golden_dataset/labels/ so run_eval.py can consume
    both without special handling.
    """
    if item.status != ReviewItemStatus.CORRECTED:
        return None

    _ensure_feedback_dir()

    # Start with whatever the extractor originally found
    original_fields: dict[str, str | None] = {}
    if item.extracted_document.claimant:
        original_fields["claimant_name"] = item.extracted_document.claimant.full_name
        original_fields["policy_number"] = item.extracted_document.claimant.policy_number

    # Apply corrections on top — these are the "right answers" the
    # adjuster provided, overriding what the system predicted.
    corrected_fields = dict(original_fields)
    for correction in item.corrections:
        corrected_fields[correction.field_name] = correction.corrected_value

    # Build the label entry
    label = {
        "example_id": f"feedback_{item.document_id}",
        "document_type": item.extracted_document.document_type.value,
        "expected_fields": {k: v for k, v in corrected_fields.items() if v is not None},
        "source": "adjuster_correction",
        "tenant_id": item.tenant_id,
        "original_extraction": {k: v for k, v in original_fields.items() if v is not None},
        "corrections_applied": [
            {
                "field_name": c.field_name,
                "original_value": c.original_value,
                "corrected_value": c.corrected_value,
                "corrected_at": c.corrected_at,
            }
            for c in item.corrections
        ],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    filename = f"feedback_{item.document_id}.json"
    path = FEEDBACK_DIR / filename
    with open(path, "w") as f:
        json.dump(label, f, indent=2)

    return path


def list_feedback_entries() -> list[dict]:
    """List all feedback-sourced golden entries."""
    _ensure_feedback_dir()
    entries = []
    for p in sorted(FEEDBACK_DIR.glob("feedback_*.json")):
        with open(p) as f:
            entries.append(json.load(f))
    return entries


def get_feedback_stats() -> dict:
    """Quick stats on how many corrections have been captured."""
    entries = list_feedback_entries()
    by_tenant: dict[str, int] = {}
    by_doc_type: dict[str, int] = {}
    for e in entries:
        tid = e.get("tenant_id", "unknown")
        dt = e.get("document_type", "unknown")
        by_tenant[tid] = by_tenant.get(tid, 0) + 1
        by_doc_type[dt] = by_doc_type.get(dt, 0) + 1

    return {
        "total_feedback_entries": len(entries),
        "by_tenant": by_tenant,
        "by_document_type": by_doc_type,
    }
