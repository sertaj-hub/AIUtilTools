"""Section-aware chunking.

Policy documents are hierarchical, and that hierarchy is the best chunk
boundary available: a section is a self-contained statement of one rule,
written by someone who intended it to be read as a unit. Fixed-width windows
cut straight through that, and the halves are worse than either the whole or a
clean split -- a window that ends mid-sentence retrieves on half a clause and
cites a rule it does not contain.

So: keep a section whole when it fits, split on paragraph then sentence
boundaries when it does not, and carry the ancestry onto every piece.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Chunk

# Roughly 1,500 characters is 350-400 tokens, comfortably inside every
# embedding model's window and small enough that a retrieved chunk is worth
# reading in full. The overlap keeps a rule that straddles a split reachable
# from either side.
DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP_CHARS = 150

# Sentence end followed by whitespace and a capital or a digit. Deliberately
# conservative: "within 30 calendar days." splits, "§ 5.1 applies" does not.
_SENTENCE_END_RE = re.compile(r"(?<=[.;:])\s+(?=[A-Z0-9])")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


class ChunkingError(ValueError):
    """The chunker was asked for something it cannot do."""


def _split_oversized(piece: str, max_chars: int) -> list[str]:
    """Break a single over-long paragraph on sentence boundaries.

    A sentence longer than the budget on its own is emitted whole rather than
    cut mid-clause. An embedding of a slightly-too-long passage is a minor
    quality cost; a citation pointing at half a sentence is a correctness one.
    """
    sentences = _SENTENCE_END_RE.split(piece)
    out: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > max_chars:
            out.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _pack(pieces: Iterable[str], max_chars: int) -> list[str]:
    """Greedily fill chunks up to the budget, never splitting a piece."""
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and len(candidate) > max_chars:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def split_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """Split `text` into pieces of at most `max_chars`, on natural boundaries."""
    if max_chars < 200:
        raise ChunkingError("max_chars must be at least 200")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ChunkingError("overlap_chars must be between 0 and max_chars")

    body = text.strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    # Pack to a reduced budget so that prepending the overlap still lands
    # inside max_chars. Without this the chunks that carry an overlap exceed
    # the budget the caller set, and max_chars stops meaning anything.
    budget = max_chars - overlap_chars if overlap_chars else max_chars

    paragraphs: list[str] = []
    for paragraph in _PARAGRAPH_RE.split(body):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        if len(cleaned) <= budget:
            paragraphs.append(cleaned)
        else:
            paragraphs.extend(_split_oversized(cleaned, budget))

    packed = _pack(paragraphs, budget)
    if overlap_chars == 0 or len(packed) == 1:
        return packed

    # Tail of the previous chunk is prepended to the next, on a word boundary,
    # so a rule that straddles the split is retrievable from either side.
    overlapped = [packed[0]]
    for previous, piece in zip(packed, packed[1:]):
        tail = previous[-overlap_chars:]
        _, _, tail = tail.partition(" ")
        overlapped.append(f"{tail.strip()} {piece}".strip() if tail.strip() else piece)
    return overlapped


def chunk_section(
    *,
    policy_id: str,
    version: str,
    number: str,
    heading: str,
    text: str,
    heading_path: tuple[str, ...],
    audience: tuple[str, ...] = (),
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Turn one section into one or more chunks, each carrying its ancestry."""
    section_id = f"{policy_id}@{version}#{number}"
    pieces = split_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    total = len(pieces)
    return [
        Chunk(
            chunk_id=section_id if total == 1 else f"{section_id}/{ordinal}",
            section_id=section_id,
            policy_id=policy_id,
            version=version,
            number=number,
            heading=heading,
            heading_path=heading_path,
            text=piece,
            ordinal=ordinal,
            total=total,
            audience=audience,
        )
        for ordinal, piece in enumerate(pieces)
    ]
