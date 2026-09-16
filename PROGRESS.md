# Progress Log

Daily entries: what got built, one decision worth remembering, one thing
that didn't work. Kept short on purpose — this is a build log, not a diary.

---

## Day 1 — Repo scaffold

**Built:**
- Repo structure for all planned components (ingestion, extraction, review, config, eval)
- `ClaimDocument` v1 Pydantic schema — the canonical data contract every later component reads/writes
- FastAPI skeleton with `/health`, `/`, and `/schema/claim-document`
- Dockerfile + docker-compose skeleton (API only; Chroma/Prometheus/Grafana added when they're actually used)
- pytest suite (3 tests) + GitHub Actions CI running it on every push

**Decision worth remembering:**
`ClaimDocument` uses per-field confidence scores (`FieldConfidence` list),
not one document-level confidence number. Reasoning: a document can be
95% confident on the claimant name and 40% confident on a smudged billed
amount. A single averaged score would either send too much to human
review (wastes adjuster time) or too little (lets real errors through).
This makes Week 2's routing logic harder to write but more honest — worth
the extra complexity now rather than retrofitting it later.

**Didn't get to:** OCR, client config loader wiring (config file exists,
loader code doesn't yet), anything resembling extraction. That's the
point of Day 1 — foundation only.

**Verified:** `uvicorn` starts, all 3 endpoints return expected responses,
`pytest tests/ -v` passes 3/3.

---

## Day 2 — Document ingestion (OCR)

**Built:**
- `app/ingestion/ocr.py` — native PDF text extraction (PyMuPDF) with automatic OCR fallback (Tesseract) per page
- `scripts/generate_sample_docs.py` — generates 4 synthetic sample claim documents (3 digital PDFs + 1 scanned-style PDF with no text layer) so the pipeline has something real to run against instead of a hardcoded string
- `POST /ingest` endpoint — upload a PDF/image, get extraction method + text back
- 6 new tests covering native extraction, OCR fallback, the API endpoint, and the unsupported-file-type error path
- Dockerfile updated to install the `tesseract-ocr` system package (pytesseract is just a wrapper — without the actual binary installed, it fails at runtime, not at `pip install` time)

**Decision worth remembering:**
Try native text extraction first, only fall back to OCR when a page comes
back with fewer than ~20 characters. OCR is slower and occasionally noisier
than reading an embedded text layer, so paying that cost only when the
document actually needs it — not on every upload — is what keeps this
approach viable at volume instead of a demo-only shortcut.

**Verified:** ran the actual HTTP endpoint (not just unit tests) against a
native PDF, a scanned PDF, and an invalid file type. Native correctly
returns `method: native`, the scanned doc correctly falls through to
`method: ocr` and Tesseract recovers the text, and the `.txt` upload
correctly 400s instead of crashing. `pytest tests/ -v` passes 9/9.

**Didn't get to:** document classification (is this an accident report
vs. a medical bill — Day 3), wiring the client config loader into the
ingestion path, structured field extraction.

**Note on Docker:** the Dockerfile change (adding `tesseract-ocr` via
apt) is untested in this environment — no Docker available here to build
and run it. Verify with `docker compose up --build` before relying on
the containerized path; if that surfaces an issue, it's a legitimate
Day 3 "Trouble" entry, not something to assume works.
