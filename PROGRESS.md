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

---

## Day 3 — Document classification

**Built:**
- `app/ingestion/classifier.py` — keyword-scoring classifier (accident
  report / policy document / medical bill), deliberately NOT an LLM call
- Wired into `/ingest`: response now includes `document_type`,
  `classification_confidence`, and raw per-type `classification_scores`
- 9 new tests, including a negative case (unrelated text must classify
  as `unknown`, never a wrong confident guess) and a parametrized check
  that all 4 real sample docs — including the OCR-derived scanned one —
  classify correctly through the full HTTP endpoint

**Decision worth remembering:** classification is rule-based, not an LLM
call, on purpose. It's free, instant, deterministic, and testable without
mocking an API — and it runs on *every* document before anything else
happens, so latency and cost compound fast if this step alone calls an
LLM. Just as important: it gives a real baseline. When an LLM-based
classifier gets considered later (for messier formats this can't handle),
there's now something concrete to measure it against, instead of
swapping in something more expensive on faith that it's better.

The other deliberate choice: unrelated/garbage text returns `unknown`
with 0.0 confidence rather than the closest-matching label. A
classifier that always outputs *something* looks more impressive in a
demo and is worse in production — it silently routes documents into the
wrong extraction schema with no signal that anything went wrong.

**Verified:** ran all 4 real sample documents through the live `/ingest`
endpoint (not just unit tests) — all classified correctly, including the
OCR-derived scanned document, proving the classifier works on noisy
real-world extracted text, not just clean synthetic strings.
`pytest tests/ -v` passes 18/18.

**Didn't get to:** wiring `document_type` into an actual `ClaimDocument`
object (still Week 2 — classification tells us *what* the document is,
not what's inside it), the client config loader, and structured field
extraction.

---

## Day 4 (interim) — Fixed CI, silently broken since Day 2

Before starting Day 4's actual scope: discovered `tests / pytest` on
GitHub Actions has been failing since Day 2's push (OCR tests added,
`tesseract-ocr` never installed on the CI runner). Fixed the workflow.
Full writeup in `MISTAKES.md`. Lesson banked: check the Actions tab
right after every push, don't rely on noticing the email eventually.

---

## Day 4 — Client config loader (multi-tenant)

**Built:**
- `app/config/schemas.py` — `ClientConfig` Pydantic model: tenant_id,
  display_name, accepted document types, review threshold, field label
  overrides
- `app/config/loader.py` — loads and validates per-tenant YAML, with an
  in-process cache, plus two custom exceptions (`TenantNotFoundError`,
  `InvalidClientConfigError`) instead of letting raw KeyErrors or
  ValidationErrors leak up
- A second real tenant config (`client_beta_insurance.yaml`) — genuinely
  different from Acme's (excludes medical bills, lower review threshold),
  specifically so the loader's multi-tenant claim has something real to
  prove against, not just one config file
- `/ingest` now requires `tenant_id`, checks the classified document type
  against that tenant's `accepted_document_types`, and returns
  `in_scope_for_tenant` + `tenant_review_threshold`
- New `/tenants` and `/tenants/{tenant_id}` endpoints
- 12 new tests, including the two realistic config-authoring mistakes
  (tenant_id/filename mismatch, out-of-range threshold) and the actual
  core proof: the identical medical bill file produces `in_scope: true`
  for Acme and `in_scope: false` for Beta through the same code path

**Decision worth remembering:** validate `ClientConfig` at LOAD time, not
at first use. A malformed config for a new client should fail loudly the
moment it's loaded — ideally the moment it's committed, once CI runs
against it — not silently three requests deep into that client's first
day live. Also added a same-file safety check: the internal `tenant_id`
field must match the filename, specifically because copy-pasting an
existing tenant's file to onboard a new one and forgetting to update one
field is exactly the kind of mistake that's easy to make and easy to
miss without an explicit check for it.

**Verified:** ran the real proof over live HTTP — same file, two tenant
IDs, genuinely different `in_scope_for_tenant` and `tenant_review_threshold`
in the response. Also caught and fixed a real regression along the way
(see `MISTAKES.md`): making `tenant_id` required broke 6 existing tests
from Day 2/3 that never passed one. `pytest tests/ -v` passes 30/30.

**Didn't get to:** actually using `review_threshold` for anything (still
Week 2 — there's no confidence-scored extraction yet to threshold
against), `field_label_overrides` isn't applied anywhere yet (nothing
renders field labels until structured extraction exists).

---

## Day 5 — Golden dataset (first 10 of ~30) + eval-driven fix

**Built:**
- `scripts/generate_golden_dataset.py` — 10 hand-labeled examples, not
  copies of Day 2's originals: normal cases, phrasing VARIANTS of the
  same document types (different headers/wording, testing whether
  classification generalizes or just pattern-matches specific strings),
  and one deliberately ambiguous document (a generic cover letter) with
  expected label `unknown`
- `eval/run_eval.py` — runs the golden set through real OCR + real
  classification, reports per-example pass/fail and overall accuracy.
  Deliberately built to grow into Week 3's full harness rather than get
  thrown away later
- 3 new tests wiring the eval itself into `pytest`, so a future
  regression in classification accuracy fails CI immediately

**What actually happened, in order — this is the real eval-driven loop:**
1. First run: **8/10 (80%)**. Both failures were phrasing variants —
   "COLLISION INCIDENT SUMMARY" and "INVOICE FOR SERVICES RENDERED" —
   neither matched any keyword in Day 3's classifier.
2. Importantly, both failures came back as `unknown`, not a wrong
   confident label — Day 3's "admit uncertainty" design held up under
   real pressure, it just meant the classifier's *coverage* was too
   narrow, not that its judgment was wrong.
3. Expanded the keyword sets in `app/ingestion/classifier.py` to cover
   the missed phrasings, plus a few adjacent real-world header variants
   (e.g. "certificate of insurance") that weren't failures yet but are
   common enough to be worth covering proactively.
4. Re-ran: **10/10 (100%)**, including the ambiguous cover-letter
   example still correctly returning `unknown` — confirming the keyword
   expansion improved coverage without eroding the honest-uncertainty
   behavior by becoming too permissive.

**Why this sequence matters more than the code:** this is the actual
shape of eval-driven development — measure, find a real gap, fix the
gap, re-measure, confirm the fix didn't break something else. It's a
small-scale preview of exactly what Week 3's CI-gated harness does at
full size, and it's genuine interview material: "tell me about a time
you used evaluation to find and fix a real gap" now has a true, specific
answer instead of a generic one.

**Verified:** `python eval/run_eval.py` shows 10/10. `pytest tests/ -v`
passes 33/33.

**Didn't get to:** the remaining ~20 golden examples (next batch happens
alongside Week 2's extraction work, once there's a field-level accuracy
to measure, not just classification), field-level ground truth isn't
evaluated yet since structured extraction doesn't exist.
