"""
Runs the golden dataset through the current pipeline (extraction +
classification) and reports how well it does against hand-labeled
ground truth.

This is a DELIBERATE early, partial version of Week 3's full eval
harness - it only checks classification accuracy right now because
that's the only stage of the pipeline that produces a labeled prediction
so far. Field-level extraction accuracy gets added here once Week 2
builds the extraction layer; this file is designed to grow into that,
not get thrown away and rewritten.

Run: python eval/run_eval.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingestion.ocr import extract_text
from app.ingestion.classifier import classify_document

DOC_DIR = Path("eval/golden_dataset/documents")
LABEL_DIR = Path("eval/golden_dataset/labels")


def run_eval() -> dict:
    label_files = sorted(LABEL_DIR.glob("*.json"))
    results = []

    for label_path in label_files:
        with open(label_path) as f:
            label = json.load(f)

        example_id = label["example_id"]
        expected_type = label["document_type"]
        pdf_path = DOC_DIR / f"{example_id}.pdf"

        extraction = extract_text(pdf_path)
        classification = classify_document(extraction.text)
        predicted_type = classification.document_type.value

        correct = predicted_type == expected_type
        results.append({
            "example_id": example_id,
            "expected": expected_type,
            "predicted": predicted_type,
            "confidence": classification.confidence,
            "correct": correct,
        })

    total = len(results)
    correct_count = sum(r["correct"] for r in results)
    accuracy = correct_count / total if total else 0.0

    return {"results": results, "accuracy": accuracy, "total": total, "correct": correct_count}


def print_report(report: dict) -> None:
    print(f"{'Example':<38} {'Expected':<18} {'Predicted':<18} {'Conf':<6} {'':<3}")
    print("-" * 90)
    for r in report["results"]:
        mark = "PASS" if r["correct"] else "FAIL"
        print(f"{r['example_id']:<38} {r['expected']:<18} {r['predicted']:<18} {r['confidence']:<6} {mark}")
    print("-" * 90)
    print(f"Classification accuracy: {report['correct']}/{report['total']} ({report['accuracy']:.1%})")

    failures = [r for r in report["results"] if not r["correct"]]
    if failures:
        print(f"\n{len(failures)} failure(s) - not necessarily bugs, may be genuine classifier limitations:")
        for f in failures:
            print(f"  {f['example_id']}: expected '{f['expected']}', got '{f['predicted']}'")


if __name__ == "__main__":
    report = run_eval()
    print_report(report)

    # Regression gate placeholder - Week 3 wires this into CI properly
    # with a real baseline. For now: fail loudly if accuracy drops below
    # a bar that would mean something is badly broken, not just imperfect.
    MINIMUM_ACCEPTABLE_ACCURACY = 0.70
    if report["accuracy"] < MINIMUM_ACCEPTABLE_ACCURACY:
        print(f"\nFAILED: accuracy {report['accuracy']:.1%} is below the {MINIMUM_ACCEPTABLE_ACCURACY:.0%} floor.")
        sys.exit(1)
