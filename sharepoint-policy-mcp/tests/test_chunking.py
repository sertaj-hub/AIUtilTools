"""Section-aware chunking: boundaries, budgets, overlap and ancestry."""

import pytest

from sharepoint_policy_mcp.chunking import ChunkingError, chunk_section, split_text

PATH = ("BSA/AML Compliance Program Policy", "5.0 Suspicious Activity", "5.1 SAR Filing Deadlines")


def paragraphs(count: int, sentence: str = "Alpha beta gamma delta epsilon. ") -> str:
    return "\n\n".join((sentence * 8).strip() for _ in range(count))


# -- split_text ----------------------------------------------------------


def test_text_within_budget_is_left_whole():
    assert split_text("A short policy clause.", max_chars=500) == [
        "A short policy clause."
    ]


def test_empty_text_produces_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_every_piece_respects_the_budget_with_overlap_on():
    pieces = split_text(paragraphs(12), max_chars=600, overlap_chars=80)
    assert len(pieces) > 1
    # The overlap is prepended after packing, so the budget must account for
    # it -- otherwise max_chars means nothing.
    assert max(len(p) for p in pieces) <= 600


def test_every_piece_respects_the_budget_with_overlap_off():
    pieces = split_text(paragraphs(12), max_chars=600, overlap_chars=0)
    assert max(len(p) for p in pieces) <= 600


def test_splits_fall_on_paragraph_boundaries():
    # Three paragraphs, each comfortably under the budget but too big to pack
    # together, so the splits can only land between them.
    one = "First paragraph. " * 12
    two = "Second paragraph. " * 12
    three = "Third paragraph. " * 12
    pieces = split_text(f"{one.strip()}\n\n{two.strip()}\n\n{three.strip()}",
                        max_chars=250, overlap_chars=0)
    assert len(pieces) == 3
    assert pieces[0].startswith("First") and pieces[0].endswith("paragraph.")
    assert pieces[1].startswith("Second")
    assert pieces[2].startswith("Third")


def test_an_oversized_paragraph_is_split_on_sentences():
    text = ("This is one sentence of policy text. " * 30).strip()
    pieces = split_text(text, max_chars=400, overlap_chars=0)
    assert len(pieces) > 1
    for piece in pieces:
        assert piece.endswith(".")


def test_a_single_sentence_over_budget_is_kept_whole():
    # An embedding of a slightly-too-long passage is a minor quality cost; a
    # citation pointing at half a sentence is a correctness one.
    monster = "word " * 300
    pieces = split_text(monster.strip(), max_chars=400, overlap_chars=0)
    assert len(pieces) == 1


def test_overlap_carries_text_from_the_previous_piece():
    pieces = split_text(paragraphs(10), max_chars=700, overlap_chars=120)
    assert len(pieces) > 1
    tail_words = pieces[0].split()[-5:]
    assert any(word in pieces[1] for word in tail_words)


def test_zero_overlap_shares_nothing():
    pieces = split_text(
        "Alpha unique-one.\n\nBeta unique-two.\n\nGamma unique-three.",
        max_chars=200,
        overlap_chars=0,
    )
    joined = " ".join(pieces)
    assert joined.count("unique-one") == 1


def test_absurd_parameters_are_refused():
    with pytest.raises(ChunkingError, match="at least 200"):
        split_text("text", max_chars=10)
    with pytest.raises(ChunkingError, match="between 0 and max_chars"):
        split_text("text", max_chars=500, overlap_chars=500)
    with pytest.raises(ChunkingError):
        split_text("text", max_chars=500, overlap_chars=-1)


# -- chunk_section -------------------------------------------------------


def kwargs(**extra):
    base = dict(
        policy_id="BSA-001",
        version="4.2",
        number="5.1",
        heading="SAR Filing Deadlines",
        heading_path=PATH,
    )
    base.update(extra)
    return base


def test_a_short_section_becomes_one_chunk_keeping_the_section_id():
    chunks = chunk_section(text="File within 30 calendar days.", **kwargs())
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "BSA-001@4.2#5.1"
    assert chunks[0].is_partial is False


def test_a_long_section_is_split_with_ordinal_suffixes():
    chunks = chunk_section(text=paragraphs(12), max_chars=600, **kwargs())
    assert len(chunks) > 1
    assert [c.chunk_id for c in chunks] == [
        f"BSA-001@4.2#5.1/{i}" for i in range(len(chunks))
    ]
    assert all(c.section_id == "BSA-001@4.2#5.1" for c in chunks)
    assert all(c.total == len(chunks) for c in chunks)
    assert all(c.is_partial for c in chunks)


def test_every_chunk_keeps_the_full_ancestry():
    # A clause split off the bottom of 5.1 must still cite 5.1.
    chunks = chunk_section(text=paragraphs(12), max_chars=600, **kwargs())
    for chunk in chunks:
        assert chunk.heading_path == PATH
        assert chunk.number == "5.1"
        assert chunk.heading == "SAR Filing Deadlines"


def test_audience_is_carried_onto_every_chunk():
    chunks = chunk_section(
        text=paragraphs(12), max_chars=600, audience=("bsa-officer",), **kwargs()
    )
    assert all(c.audience == ("bsa-officer",) for c in chunks)


def test_as_section_exposes_the_ancestry_to_the_lexical_index():
    chunk = chunk_section(text="Short clause.", **kwargs())[0]
    section = chunk.as_section()
    assert section.section_id == chunk.chunk_id
    # A chunk of 5.1 should still match a query for "suspicious activity",
    # which only appears in the parent heading.
    assert "Suspicious Activity" in section.heading


def test_empty_section_text_produces_no_chunks():
    assert chunk_section(text="   ", **kwargs()) == []
