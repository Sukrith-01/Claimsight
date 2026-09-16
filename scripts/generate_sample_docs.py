"""
Generates synthetic sample claim documents for local dev and testing.

These are NOT real insurance documents (obviously) - they're realistic
enough text laid out like the real thing, so the ingestion pipeline has
something honest to chew on instead of a one-line toy string. Three are
"digital" PDFs (real text layer, like an e-filed document); one is
deliberately flattened to an image-only PDF with no text layer, to
exercise the OCR fallback path the same way an actual scanned fax or
phone photo of a document would.

Run: python scripts/generate_sample_docs.py
"""

import pymupdf as fitz  # PyMuPDF - `import fitz` directly is deprecated as of 2024
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT_DIR = "data/sample_docs"


def make_text_pdf(path: str, lines: list[str]) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica", 11)
    y = 740
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()


def flatten_pdf_to_image_only(source_path: str, dest_path: str) -> None:
    """
    Renders a text PDF to a raster image, then builds a NEW pdf containing
    only that image - i.e. a PDF with no extractable text layer at all.
    This is what a scanned/faxed document looks like to a parser: pixels,
    not characters.
    """
    src = fitz.open(source_path)
    page = src[0]
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("jpeg", jpg_quality=85)  # JPEG, not PNG: ~10x smaller, plenty legible for OCR
    src.close()

    doc = fitz.open()
    new_page = doc.new_page(width=pix.width, height=pix.height)
    new_page.insert_image(new_page.rect, stream=img_bytes)
    doc.save(dest_path)
    doc.close()


ACCIDENT_REPORT = [
    "ACCIDENT REPORT",
    "",
    "Claimant Name: Maria Gonzalez",
    "Date of Birth: 03/14/1987",
    "Policy Number: ACM-4471829",
    "",
    "Incident Date: 08/22/2026",
    "Location: Intersection of 5th Ave and Main St, Tallahassee, FL",
    "Description: Rear-end collision at a stoplight. Claimant's vehicle",
    "was stationary when struck from behind by another driver.",
    "",
    "Reporting Officer: Badge #2214",
    "Report Filed: 08/22/2026",
]

POLICY_DOCUMENT = [
    "AUTO INSURANCE POLICY SUMMARY",
    "",
    "Policyholder: Maria Gonzalez",
    "Policy Number: ACM-4471829",
    "Coverage Period: 01/01/2026 - 01/01/2027",
    "",
    "Liability Coverage: $100,000 / $300,000",
    "Collision Coverage: $50,000 (Deductible: $500)",
    "Comprehensive Coverage: $50,000 (Deductible: $250)",
    "",
    "Insurer: Acme Insurance Co.",
    "Underwriting Office: Tallahassee, FL",
]

MEDICAL_BILL = [
    "MEDICAL BILLING STATEMENT",
    "",
    "Patient Name: Maria Gonzalez",
    "Date of Birth: 03/14/1987",
    "Date of Service: 08/23/2026",
    "",
    "Provider: Capital Regional Urgent Care",
    "",
    "Line Items:",
    "  Emergency Room Visit - Level 3      $1,240.00   Dx: S13.4XXA",
    "  X-Ray, Cervical Spine                 $310.00   Dx: S13.4XXA",
    "  Physical Therapy Consult              $185.00   Dx: M54.2",
    "",
    "Total Billed: $1,735.00",
]


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    make_text_pdf(f"{OUT_DIR}/accident_report_sample.pdf", ACCIDENT_REPORT)
    make_text_pdf(f"{OUT_DIR}/policy_document_sample.pdf", POLICY_DOCUMENT)
    make_text_pdf(f"{OUT_DIR}/medical_bill_sample.pdf", MEDICAL_BILL)

    # Scanned-style version of the accident report - no text layer,
    # forces the OCR fallback path.
    flatten_pdf_to_image_only(
        f"{OUT_DIR}/accident_report_sample.pdf",
        f"{OUT_DIR}/accident_report_scanned.pdf",
    )

    print(f"Generated 4 sample documents in {OUT_DIR}/")


if __name__ == "__main__":
    main()
