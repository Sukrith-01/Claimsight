"""
Splits raw extracted text into overlapping chunks for embedding and
retrieval.

Why overlap matters: a sentence describing something important (e.g. a
policy number right at a chunk boundary) shouldn't get split so that
neither chunk contains the full context. Overlapping windows trade some
redundant storage for not silently losing meaning at arbitrary cut
points - a real cost worth taking deliberately, not an accident of
"whatever chunk size felt reasonable."
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    chunk_index: int
    start_char: int
    end_char: int


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[Chunk]:
    """
    Splits text into overlapping chunks of roughly `chunk_size` characters,
    with `overlap` characters shared between consecutive chunks.

    Character-based, not token-based, deliberately for now: it's simpler,
    dependency-free, and good enough for the document sizes this project
    handles (single-page-ish claim documents, not 200-page contracts).
    Token-based chunking (matching what the embedding model actually
    counts) would be the right upgrade if/when documents get much longer
    or an LLM's context window becomes the binding constraint - not
    needed yet, worth flagging as a known simplification rather than
    silently pretending it doesn't matter.
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be smaller than chunk_size ({chunk_size})")

    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [Chunk(text=text, chunk_index=0, start_char=0, end_char=len(text))]

    chunks: list[Chunk] = []
    start = 0
    index = 0
    step = chunk_size - overlap

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_str = text[start:end]
        chunks.append(Chunk(text=chunk_str, chunk_index=index, start_char=start, end_char=end))

        if end == len(text):
            break

        start += step
        index += 1

    return chunks
