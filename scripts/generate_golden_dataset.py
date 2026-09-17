"""
Generates the first 10 of ~30 golden dataset examples for the eval
harness (full harness lands Week 3, but the dataset itself starts now -
it's the thing everything else gets measured against, so it's worth
building deliberately rather than rushing it later).

Design decision: this is NOT 10 copies of the same 3 templates from
Day 2. Real insurance documents don't all use identical headers and
phrasing - different offices, different software, different eras of a
client's own paperwork. So this set deliberately includes:
  - "normal" documents close to what the classifier already sees (Day 2's originals)
  - phrasing VARIANTS of the same document types (different headers,
    different wording) to test whether the classifier generalizes or
    just pattern-matches specific strings
  - ONE genuinely ambiguous document that isn't cleanly any of the three
    types, with expected_document_type = "unknown" - a direct test of
    the classifier's "admit uncertainty rather than guess" design
    decision from Day 3, using real eval data instead of one hardcoded
    unit test string

Each example is a PDF (in documents/) plus a hand-labeled JSON ground
truth file (in labels/) with the same base filename.
"""

import json
import os

import pymupdf as fitz
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

DOC_DIR = "eval/golden_dataset/documents"
LABEL_DIR = "eval/golden_dataset/labels"


def make_text_pdf(path: str, lines: list[str]) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica", 11)
    y = 740
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()


def write_label(example_id: str, document_type: str, expected_fields: dict) -> None:
    with open(f"{LABEL_DIR}/{example_id}.json", "w") as f:
        json.dump(
            {
                "example_id": example_id,
                "document_type": document_type,
                "expected_fields": expected_fields,
            },
            f,
            indent=2,
        )


EXAMPLES = [
    # --- accident reports: normal, phrasing variant, minimal ---
    (
        "claim_001_accident_normal",
        "accident_report",
        {"claimant_name": "James Whitfield", "policy_number": "ACM-1182734"},
        [
            "ACCIDENT REPORT",
            "",
            "Claimant Name: James Whitfield",
            "Policy Number: ACM-1182734",
            "Incident Date: 03/11/2026",
            "Location: Highway 27, Tallahassee, FL",
            "Description: Side collision at intersection during turn.",
            "Reporting Officer: Badge #4471",
        ],
    ),
    (
        "claim_002_accident_phrasing_variant",
        "accident_report",
        {"claimant_name": "Priya Nair", "policy_number": "ACM-9982211"},
        [
            "COLLISION INCIDENT SUMMARY",  # deliberately different header than "ACCIDENT REPORT"
            "",
            "Driver Involved: Priya Nair",
            "Reference Number: ACM-9982211",
            "Date of Occurrence: 04/02/2026",
            "Where it happened: Parking garage, level 3",
            "What happened: Vehicle struck a concrete pillar while reversing.",
            "Filed by: Officer Badge #1190",
        ],
    ),
    (
        "claim_003_accident_minimal",
        "accident_report",
        {"claimant_name": "Tom Reyes"},
        [
            "ACCIDENT REPORT",
            "",
            "Claimant Name: Tom Reyes",
            "Incident Date: 05/19/2026",
            "Description: Minor collision, no injuries reported.",
        ],
    ),
    # --- policy documents: normal, phrasing variant, minimal ---
    (
        "claim_004_policy_normal",
        "policy_document",
        {"policyholder": "James Whitfield", "policy_number": "ACM-1182734"},
        [
            "AUTO INSURANCE POLICY SUMMARY",
            "",
            "Policyholder: James Whitfield",
            "Policy Number: ACM-1182734",
            "Coverage Period: 01/01/2026 - 01/01/2027",
            "Liability Coverage: $100,000 / $300,000",
            "Deductible: $500",
            "Underwriting Office: Tallahassee, FL",
        ],
    ),
    (
        "claim_005_policy_phrasing_variant",
        "policy_document",
        {"policyholder": "Priya Nair", "policy_number": "ACM-9982211"},
        [
            "CERTIFICATE OF INSURANCE",  # different header than "POLICY SUMMARY"
            "",
            "Insured Party: Priya Nair",
            "Certificate Number: ACM-9982211",
            "Effective Dates: 02/15/2026 through 02/15/2027",
            "Comprehensive Coverage: $50,000",
            "Deductible Amount: $250",
        ],
    ),
    (
        "claim_006_policy_minimal",
        "policy_document",
        {"policyholder": "Tom Reyes"},
        [
            "AUTO INSURANCE POLICY SUMMARY",
            "",
            "Policyholder: Tom Reyes",
            "Coverage Period: 03/01/2026 - 03/01/2027",
            "Liability Coverage: $50,000 / $100,000",
        ],
    ),
    # --- medical bills: normal, phrasing variant, minimal ---
    (
        "claim_007_medical_normal",
        "medical_bill",
        {"patient_name": "James Whitfield", "total_billed": "$2,140.00"},
        [
            "MEDICAL BILLING STATEMENT",
            "",
            "Patient Name: James Whitfield",
            "Date of Service: 03/12/2026",
            "Provider: Tallahassee Emergency Care",
            "Line Items:",
            "  Emergency Room Visit           $1,890.00   Dx: S13.4XXA",
            "  X-Ray, Lumbar Spine              $250.00   Dx: S13.4XXA",
            "Total Billed: $2,140.00",
        ],
    ),
    (
        "claim_008_medical_phrasing_variant",
        "medical_bill",
        {"patient_name": "Priya Nair", "total_billed": "$615.00"},
        [
            "INVOICE FOR SERVICES RENDERED",  # different header than "MEDICAL BILLING STATEMENT"
            "",
            "Patient: Priya Nair",
            "Service Date: 04/03/2026",
            "Rendered By: Capital Orthopedic Group",
            "Charges:",
            "  Consultation                    $185.00   Code: M25.561",
            "  Physical Therapy Session         $430.00   Code: M25.561",
            "Amount Due: $615.00",
        ],
    ),
    (
        "claim_009_medical_minimal",
        "medical_bill",
        {"patient_name": "Tom Reyes"},
        [
            "MEDICAL BILLING STATEMENT",
            "",
            "Patient Name: Tom Reyes",
            "Total Billed: $340.00",
        ],
    ),
    # --- the deliberately ambiguous case ---
    (
        "claim_010_ambiguous_cover_letter",
        "unknown",
        {},
        [
            "Dear Valued Customer,",
            "",
            "Thank you for choosing us for your insurance needs. We are",
            "committed to providing excellent service and support.",
            "",
            "If you have any questions, please contact our customer",
            "service team at your convenience.",
            "",
            "Sincerely,",
            "Customer Relations Department",
        ],
    ),
]


def main():
    os.makedirs(DOC_DIR, exist_ok=True)
    os.makedirs(LABEL_DIR, exist_ok=True)

    for example_id, doc_type, expected_fields, lines in EXAMPLES:
        make_text_pdf(f"{DOC_DIR}/{example_id}.pdf", lines)
        write_label(example_id, doc_type, expected_fields)

    print(f"Generated {len(EXAMPLES)} golden dataset examples in {DOC_DIR}/ and {LABEL_DIR}/")


if __name__ == "__main__":
    main()
