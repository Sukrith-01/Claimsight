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
