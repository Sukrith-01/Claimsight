"""
Document ingestion: get raw text out of a PDF or image, whatever shape it
arrives in.

Design decision: try native text extraction FIRST (fast, free, perfectly
accurate when the PDF has a real text layer), and only fall back to OCR
when native extraction comes back too thin to be real content. This
matters in production: OCR is slow and occasionally wrong in ways plain
text extraction never is, so paying that cost only when actually
necessary - not on every document - is the difference between a pipeline
that scales and one that doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
import pytesseract
from PIL import Image

# Below this many characters per page, assume the "text" extracted was
# noise (e.g. a stray header) rather than real content, and treat the
# page as needing OCR. Tuned loosely - real documents will average
# hundreds of characters per page; scanned pages with no text layer
# return ~0.
MIN_CHARS_PER_PAGE_THRESHOLD = 20


@dataclass
class ExtractionResult:
    text: str
    method: str  # "native" | "ocr" | "mixed"
    page_count: int
    pages_ocr_count: int  # how many pages needed OCR fallback


def extract_from_pdf(path: str | Path) -> ExtractionResult:
    """
    Extract text from a PDF, page by page, using native extraction where
    possible and OCR where the page has no usable text layer.
    """
    doc = fitz.open(str(path))
    page_texts: list[str] = []
    pages_ocr_count = 0

    for page in doc:
        native_text = page.get_text().strip()

        if len(native_text) >= MIN_CHARS_PER_PAGE_THRESHOLD:
            page_texts.append(native_text)
            continue

        # Fall back to OCR: render the page to an image, run tesseract.
        pix = page.get_pixmap(dpi=300)  # higher DPI = better OCR accuracy, worth the cost here
        img_bytes = pix.tobytes("png")
        import io
        image = Image.open(io.BytesIO(img_bytes))
        ocr_text = pytesseract.image_to_string(image).strip()
        page_texts.append(ocr_text)
        pages_ocr_count += 1

    page_count = len(doc)
    doc.close()

    if pages_ocr_count == 0:
        method = "native"
    elif pages_ocr_count == page_count:
        method = "ocr"
    else:
        method = "mixed"

    return ExtractionResult(
        text="\n\n".join(page_texts),
        method=method,
        page_count=page_count,
        pages_ocr_count=pages_ocr_count,
    )


def extract_from_image(path: str | Path) -> ExtractionResult:
    """Extract text from a standalone image file (jpg/png) - always OCR, there's no 'native' text in a raw photo."""
    image = Image.open(str(path))
    text = pytesseract.image_to_string(image).strip()
    return ExtractionResult(text=text, method="ocr", page_count=1, pages_ocr_count=1)


def extract_text(path: str | Path) -> ExtractionResult:
    """Entry point: dispatches to the right extractor based on file extension."""
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return extract_from_pdf(p)
    elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
        return extract_from_image(p)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Expected .pdf, .png, .jpg, .jpeg, .tiff, or .bmp")
