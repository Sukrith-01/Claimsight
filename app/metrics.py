"""
Prometheus metrics for ClaimSight.

Four metrics, each chosen because it answers a question an operator
or client would actually ask:

1. ingest_total (counter): how many documents have been processed,
   by tenant and document type? This is the throughput number.
2. ingest_duration_seconds (histogram): how long does ingestion take?
   Broken out by extraction method (native vs OCR) because OCR is
   meaningfully slower and worth monitoring separately.
3. review_queue_depth (gauge): how many items are waiting for human
   review per tenant? A growing queue means either the system's
   confidence is too low (threshold too strict) or adjusters aren't
   keeping up.
4. extraction_confidence (histogram): distribution of confidence
   scores. If this shifts left over time, the extraction pipeline
   is degrading.
"""

from prometheus_client import Counter, Histogram, Gauge

INGEST_TOTAL = Counter(
    "claimsight_ingest_total",
    "Total documents ingested",
    ["tenant_id", "document_type"],
)

INGEST_DURATION = Histogram(
    "claimsight_ingest_duration_seconds",
    "Time to process one document through the full ingestion pipeline",
    ["extraction_method"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

REVIEW_QUEUE_DEPTH = Gauge(
    "claimsight_review_queue_depth",
    "Number of items pending human review",
    ["tenant_id"],
)

EXTRACTION_CONFIDENCE = Histogram(
    "claimsight_extraction_confidence",
    "Distribution of extraction confidence scores",
    ["tenant_id"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
