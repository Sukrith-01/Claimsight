# ClaimSight

Multi-tenant insurance claims document intelligence platform. Ingests messy
claim documents (accident reports, policy PDFs, medical bills), extracts
structured data, scores confidence per field, and routes low-confidence
extractions to human review — with per-client schemas driven by config,
not forked code.

**Status:** Day 9 — human review queue is live. Low-confidence
extractions auto-route from /ingest into a tenant-scoped review queue.
Adjusters can view pending items, submit corrections (appended for
audit trail, never overwriting the original), or approve as-is. See
`PROGRESS.md` for the running log.

## Architecture (target — most pieces not built yet)

```mermaid
flowchart TB
    subgraph Ingestion
        A[Upload: PDF/Image] --> B[OCR / Text Extraction]
        B --> C[Document Classifier]
    end
    subgraph "Extraction Layer"
        C --> D[Client Config Loader]
        D --> E[Chunking + Embedding]
        E --> F[Vector Store]
        C --> G[Structured Extraction - LLM + Schema]
        F -.retrieval context.-> G
        G --> H[Confidence Scorer]
    end
    subgraph "Review & Feedback"
        H -->|high confidence| I[Auto-Approved Claim Record]
        H -->|low confidence| J[Human Review Queue]
        J --> K[Adjuster Correction]
        K --> L[Feedback Store]
        L -.improves.-> G
    end
    subgraph "Observability"
        I --> M[Eval Harness / CI]
        H --> N[Monitoring Dashboard]
    end
```

## Run it locally

```bash
pip install -r requirements.txt
python scripts/generate_sample_docs.py   # creates data/sample_docs/
uvicorn app.main:app --reload
```

Then:
- `GET /health` — liveness check
- `GET /` — service info
- `GET /schema/claim-document` — current `ClaimDocument` JSON schema
- `GET /tenants` — list configured tenants
- `GET /tenants/{tenant_id}` — inspect one tenant's config
- `POST /ingest` — upload a PDF/image + a `tenant_id`, get back extracted
  text, extraction method, classified document type, whether that type
  is `in_scope_for_tenant`, chunks indexed for search, and (new) extracted
  structured fields (`extracted_fields`) with a `requires_review` flag
  based on the tenant's configured confidence threshold
- `POST /search` — query previously-ingested documents for a tenant;
  results are hard-filtered to that tenant, never cross-tenant
- `GET /docs` — interactive API docs (FastAPI auto-generated)

See the actual multi-tenant behavior — same file, different tenant, different result:
```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@data/sample_docs/medical_bill_sample.pdf" -F "tenant_id=acme_insurance"
# -> in_scope_for_tenant: true (Acme's contract covers medical bills)

curl -X POST http://localhost:8000/ingest \
  -F "file=@data/sample_docs/medical_bill_sample.pdf" -F "tenant_id=beta_insurance"
# -> in_scope_for_tenant: false (Beta's contract doesn't)
```

Try the OCR fallback path specifically:
```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@data/sample_docs/accident_report_scanned.pdf" -F "tenant_id=acme_insurance"
```

Ingest a document, then search for it:
```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@data/sample_docs/accident_report_sample.pdf" -F "tenant_id=acme_insurance"

curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "acme_insurance", "query": "vehicle collision at an intersection"}'
```

**Note on embeddings:** the default embedder (`HashingEmbedder`) is a
deterministic, dependency-free local implementation - no API key, no
network call, no cost. It's a real design tradeoff, not a shortcut: see
the docstring in `app/extraction/embeddings.py` for why, and how a real
hosted embedding API slots in later via the same interface.

## Run it via Docker

```bash
docker compose up --build
```

## Run tests

```bash
pytest tests/ -v
```

## Run the eval harness

```bash
python scripts/generate_golden_dataset.py   # if not already generated
python eval/run_eval.py
```

Reports classification accuracy against 10 hand-labeled examples
(normal cases, phrasing variants, and one deliberately ambiguous
document that should classify as `unknown`). Grows into a full
extraction-accuracy harness in Week 3.

## Project layout

```
claimsight/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── models/schemas.py    # canonical ClaimDocument data contract
│   ├── ingestion/           # OCR + document classification (Week 1)
│   ├── extraction/          # chunking, embeddings, LLM extraction (Week 2)
│   ├── review/               # human review queue + feedback (Week 2)
│   └── config/                # per-tenant config loader (Week 1)
├── configs/                    # per-client YAML configs
├── eval/                        # golden dataset + eval harness (Week 3)
├── tests/
└── .github/workflows/          # CI
```

## Why this exists

Built as a demonstration of forward-deployed / applied-AI engineering:
taking an ambiguous client problem (extract structured data from
inconsistent insurance paperwork) and shipping a system that's
production-shaped from day one — typed data contracts, per-tenant
configuration instead of forked code, confidence-aware automation instead
of blind trust in LLM output, and an evaluation harness that gates changes
in CI rather than "looks fine in the demo."

Full build log in `PROGRESS.md`. Notable bugs and the lessons from them in
`MISTAKES.md`.
