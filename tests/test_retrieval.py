"""
Day 6 tests: chunking, embeddings, vector store, and the /search endpoint.

The most important test here isn't "does search return results" - it's
test_search_never_leaks_across_tenants, which is the retrieval-layer
half of the multi-tenant promise from Day 4. A config loader that
restricts document TYPES means nothing if the vector store happily
returns Tenant A's content to Tenant B's query.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.extraction.chunking import chunk_text
from app.extraction.embeddings import HashingEmbedder
from app.extraction.retriever import VectorStore

client = TestClient(app)


# --- chunking ---

def test_short_text_is_one_chunk():
    chunks = chunk_text("short text here", chunk_size=500, overlap=100)
    assert len(chunks) == 1


def test_long_text_splits_with_overlap():
    long_text = "word " * 300  # well over default chunk_size
    chunks = chunk_text(long_text, chunk_size=200, overlap=50)
    assert len(chunks) > 1
    # verify actual overlap: end of chunk N should match start of chunk N+1
    overlap_region = chunks[0].text[-50:]
    assert overlap_region == chunks[1].text[:50]


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, overlap=100)


# --- embeddings ---

def test_embedding_is_deterministic():
    embedder = HashingEmbedder()
    v1 = embedder.embed(["the same text"])[0]
    v2 = embedder.embed(["the same text"])[0]
    assert v1 == v2


def test_embedding_has_correct_dimension():
    embedder = HashingEmbedder(dimension=384)
    v = embedder.embed(["some text"])[0]
    assert len(v) == 384


def test_similar_text_scores_higher_than_unrelated_text():
    embedder = HashingEmbedder()
    a, b, c = embedder.embed([
        "collision at the intersection",
        "a collision occurred near the intersection",
        "total billed amount for medical services",
    ])
    sim_ab = sum(x * y for x, y in zip(a, b))
    sim_ac = sum(x * y for x, y in zip(a, c))
    assert sim_ab > sim_ac


# --- vector store ---

def test_index_and_search_finds_relevant_chunk():
    store = VectorStore()
    store.index_document("doc1", "test_tenant", "ACCIDENT REPORT\nCollision at Main St intersection.")
    results = store.search("car crash at an intersection", tenant_id="test_tenant", top_k=1)
    assert len(results) == 1
    assert "Collision" in results[0].text


def test_search_never_leaks_across_tenants():
    """
    THE critical test: index different content for two tenants, search
    one, confirm zero results ever come from the other tenant - even
    when the query would clearly match the other tenant's content.
    """
    store = VectorStore()
    store.index_document("doc_a", "tenant_a", "ACCIDENT REPORT: collision at the intersection on Main St.")
    store.index_document("doc_b", "tenant_b", "MEDICAL BILLING STATEMENT: total billed $500.")

    results_a = store.search("collision intersection", tenant_id="tenant_a", top_k=5)
    results_b = store.search("collision intersection", tenant_id="tenant_b", top_k=5)

    assert all(r.tenant_id == "tenant_a" for r in results_a)
    assert all(r.tenant_id == "tenant_b" for r in results_b)
    # tenant_b has no accident-related content at all - confirms no fallback leakage
    assert all("collision" not in r.text.lower() for r in results_b)


# --- API endpoints ---

def test_ingest_indexes_document_and_returns_chunk_count():
    with open("data/sample_docs/accident_report_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("accident_report_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["chunks_indexed"] >= 1
    assert "document_id" in body


def test_search_endpoint_returns_relevant_results():
    # ingest first so there's something to find
    with open("data/sample_docs/accident_report_sample.pdf", "rb") as f:
        client.post(
            "/ingest",
            files={"file": ("accident_report_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )

    response = client.post("/search", json={
        "tenant_id": "acme_insurance",
        "query": "vehicle collision",
        "top_k": 3,
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) >= 1


def test_search_endpoint_rejects_unknown_tenant():
    response = client.post("/search", json={
        "tenant_id": "not_a_real_tenant",
        "query": "anything",
    })
    assert response.status_code == 404
