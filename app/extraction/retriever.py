"""
Wraps ChromaDB for indexing and searching document chunks.

Two design decisions worth flagging:

1. Embeddings are computed manually and passed to Chroma explicitly,
   rather than letting Chroma use its own default embedding function.
   Chroma's default tries to download a model from Hugging Face at
   first use - a network dependency this project's embedder
   (app/extraction/embeddings.py) deliberately avoids. Passing
   embeddings explicitly keeps this dependency-free and CI-safe.

2. Every chunk is indexed with `tenant_id` in its metadata, and every
   search is filtered by tenant_id. This is the retrieval-layer half of
   the multi-tenant story from Day 4: a config loader alone doesn't stop
   Tenant A's documents from showing up in Tenant B's search results if
   the vector store itself doesn't enforce the boundary. Filtering at
   the metadata level, not just trusting the query, is what makes tenant
   isolation real instead of assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

import chromadb

from app.extraction.chunking import chunk_text
from app.extraction.embeddings import Embedder, HashingEmbedder


@dataclass
class SearchResult:
    text: str
    document_id: str
    tenant_id: str
    chunk_index: int
    score: float  # similarity score, higher = more similar


class VectorStore:
    def __init__(self, embedder: Embedder | None = None, persist_directory: str | None = None):
        self.embedder = embedder or HashingEmbedder()
        # In-memory by default (fine for dev/CI); pass persist_directory
        # for a real deployment that needs the index to survive a restart.
        self._client = (
            chromadb.PersistentClient(path=persist_directory)
            if persist_directory
            else chromadb.Client()
        )
        self._collection = self._client.get_or_create_collection("claim_chunks")

    def index_document(self, document_id: str, tenant_id: str, text: str) -> int:
        """Chunks the document text and indexes each chunk. Returns the number of chunks indexed."""
        chunks = chunk_text(text)
        if not chunks:
            return 0

        embeddings = self.embedder.embed([c.text for c in chunks])
        ids = [f"{tenant_id}:{document_id}:{c.chunk_index}" for c in chunks]
        metadatas = [
            {"tenant_id": tenant_id, "document_id": document_id, "chunk_index": c.chunk_index}
            for c in chunks
        ]

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=metadatas,
        )
        return len(chunks)

    def search(self, query: str, tenant_id: str, top_k: int = 3) -> list[SearchResult]:
        """
        Searches for chunks most similar to the query, SCOPED TO ONE TENANT.
        A query never sees another tenant's documents, regardless of how
        similar the content might be - tenant_id is a hard filter, not a
        ranking signal.
        """
        query_embedding = self.embedder.embed([query])[0]

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"tenant_id": tenant_id},
        )

        search_results = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                distance = results["distances"][0][i]
                # Chroma returns squared L2 distance by default over normalized
                # vectors; convert to a similarity score where higher = better,
                # so callers don't have to remember "lower distance = more similar."
                similarity = 1.0 - (distance / 2.0)
                metadata = results["metadatas"][0][i]
                search_results.append(SearchResult(
                    text=results["documents"][0][i],
                    document_id=metadata["document_id"],
                    tenant_id=metadata["tenant_id"],
                    chunk_index=metadata["chunk_index"],
                    score=round(similarity, 4),
                ))
        return search_results
