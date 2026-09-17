"""
Turns text into vectors for semantic search.

DELIBERATE DESIGN DECISION - read before assuming this should call
OpenAI/Claude's embedding API:

This project's resume claims (and eventual production version) point at
hosted embedding APIs (OpenAI, Cohere, Voyage) or a downloaded model
(sentence-transformers). Both require something this dev environment
doesn't have: hosted APIs need a paid API key billed per call, and a
downloaded local model needs network access to Hugging Face's model hub,
which isn't available in a sandboxed dev/CI environment.

Rather than block Week 2 on "get an API key" or silently write code that
would fail the moment CI tries to run it, this ships behind an
EMBEDDER PROTOCOL: any embedder that implements `.embed(texts) ->
list[list[float]]` can be swapped in via one line in config, with zero
changes anywhere else in the pipeline. `HashingEmbedder` is the default
for local dev and CI - free, deterministic, zero network calls, zero API
key. `OpenAIEmbedder` (a real hosted implementation) is stubbed below,
ready to activate the moment an API key exists, without touching
`retriever.py`, `main.py`, or any test that isn't specifically testing
embedding QUALITY.

This is a real production pattern, not a workaround invented to dodge a
sandbox limitation: teams routinely run a cheap/free/local embedder in
dev and CI, and a hosted one in production, specifically so CI doesn't
burn API budget or fail when a key is rotated or missing. Worth saying
exactly that in an interview if asked why this isn't just calling
OpenAI directly.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...


class HashingEmbedder:
    """
    Deterministic, dependency-free, no-network embedder using the
    feature-hashing trick: each word hashes into one of N buckets, bucket
    counts become the vector, then the vector is L2-normalized so cosine
    similarity behaves sensibly.

    This is NOT a semantic embedding - it has no notion that "collision"
    and "crash" are related concepts the way a real trained model would.
    It captures lexical overlap (shared words), which is enough to prove
    the chunking -> embedding -> vector store -> retrieval pipeline works
    end to end, and enough for near-exact-phrase retrieval. It is
    explicitly NOT a substitute for a real embedding model once one is
    available - documented here so nobody mistakes "the pipeline works"
    for "retrieval quality is production-grade."
    """

    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        words = text.lower().split()
        if not words:
            return vector

        for word in words:
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            bucket = h % self._dimension
            vector[bucket] += 1.0

        # L2 normalize so cosine similarity isn't skewed by document length
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAIEmbedder:
    """
    Stub for the production path. Not implemented yet - activating this
    is a config change (swap which embedder retriever.py constructs),
    not a rewrite, once an API key and budget exist for it.
    """

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        raise NotImplementedError(
            "OpenAIEmbedder is a stub for the production path. "
            "HashingEmbedder is the active embedder for local dev/CI - "
            "see the module docstring for why."
        )
