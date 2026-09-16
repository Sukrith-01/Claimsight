# Mistakes Log

One entry per real bug. Format: what broke → root cause → the category of
mistake, so the same class of error gets recognized faster next time.

This file starts empty. That's expected on Day 1 — it fills in as the
project hits real problems, which is the point of keeping it.

---

<!-- Example entry format, delete once the first real one lands:

## [Date] — Confidence scores all returned 0.0

**What broke:** every extracted field showed 0.0 confidence regardless of input.

**Root cause:** default value in Pydantic Field was mistakenly copied into
every response object as a *shared mutable default*.

**Category:** mutable default argument. Classic Python footgun — watch for
it anywhere a Field/dataclass default is a list, dict, or another model
instance instead of an immutable value.

-->

## Day 2 — Scanned-sample generator produced an 11MB file from a one-page document

**What broke:** `scripts/generate_sample_docs.py` initially used
`pix.tobytes("png")` to embed the rendered page image into the
"scanned" test PDF. A single page at 200 DPI came out to **11MB** — for
comparison, the real text-based PDFs in the same script are under 2KB
each. Not a crash, just quietly absurd file size that would have sat in
the repo unnoticed if I hadn't looked at `ls -la` output.

**Root cause:** PNG is lossless and doesn't compress photographic/scanned
imagery well. A raster page image doesn't need pixel-perfect losslessness
to stay OCR-legible — it needs to be readable, not identical.

**Fix:** switched to `pix.tobytes("jpeg", jpg_quality=85)`. Same OCR
accuracy on the fallback test, ~100x smaller file (11MB → 110KB).

**Category:** wrong-format-for-the-job, not a bug in the traditional
sense — the code was "correct," it just picked a format that doesn't
matter for lossless fidelity over one that's 10x smaller for a use case
(OCR input) that never needed lossless in the first place. Worth
remembering any time a task involves generating or storing document
images: match the compression to what the image is actually needed
for, not just whatever the library defaults to.