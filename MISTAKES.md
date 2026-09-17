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

---

## Day 4 — CI silently failing since Day 2, only just noticed

**What broke:** GitHub Actions' `tests / pytest` job started failing the
moment OCR tests were added — that's **Day 2**, not today. It kept
failing on Day 3's push too. It just wasn't caught until Day 4, when a
GitHub notification email finally got noticed.

**Root cause:** `.github/workflows/tests.yml` (written Day 1, before any
OCR code existed) only ran `pip install -r requirements.txt`. It never
installed the actual `tesseract` binary on the CI runner. `pytesseract`
is a thin Python wrapper — it calls out to a real Tesseract program that
has to exist on the machine separately, the same binary that needed a
manual installer on Windows locally. GitHub's runner starts from a bare
Ubuntu image every run; nothing outside `requirements.txt` exists there
unless a workflow step explicitly installs it.

**Fix:** added a `sudo apt-get install -y tesseract-ocr` step to the
workflow, before the pip install, so the runner has the same OCR engine
locally-installed via UB-Mannheim's installer.

**Category:** environment drift between "works on my machine" and CI —
the same root category as the Python 3.14 pydantic-core failure from
Day 2, just showing up on the CI side instead of the local dev side this
time. General principle worth keeping: any dependency that isn't a pure
Python package (a system binary, an OS library, a compiler) needs to be
explicitly installed in EVERY environment that runs the code — local
machine, CI, and later the Docker container — not just the one you
happened to set up by hand first.

**Process lesson, not just a technical one:** a CI failure that sits
unnoticed for two days provides zero value — the whole point of gating
on CI is catching problems before they compound, not after. Going
forward: check the Actions tab (or the email) right after every push,
not "whenever."