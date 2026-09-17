"""
Day 5 test: the golden dataset eval itself is now part of the suite, not
just something run by hand. This is a light version of what Week 3
formalizes as a real CI gate - a change that quietly regresses
classification accuracy should fail tests NOW, not get discovered later
staring at a printed report.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.run_eval import run_eval


def test_golden_dataset_has_10_examples():
    report = run_eval()
    assert report["total"] == 10


def test_classification_accuracy_meets_floor():
    """
    Not a demand for perfection - a floor. 70% is deliberately generous
    right now; Week 3 replaces this with a measured baseline once the
    full 30-example dataset and field-level extraction exist. The point
    today is that a real regression (e.g. someone breaks the keyword
    list) fails a test immediately instead of silently degrading.
    """
    report = run_eval()
    assert report["accuracy"] >= 0.70


def test_ambiguous_document_correctly_returns_unknown():
    """
    The specific case worth protecting explicitly: the deliberately
    ambiguous cover-letter example must classify as unknown, not get
    swept into a false positive as keyword coverage grows over time.
    """
    report = run_eval()
    ambiguous_result = next(
        r for r in report["results"] if r["example_id"] == "claim_010_ambiguous_cover_letter"
    )
    assert ambiguous_result["predicted"] == "unknown"
    assert ambiguous_result["correct"] is True
