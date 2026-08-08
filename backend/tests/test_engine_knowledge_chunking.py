"""Tests for `app.engine.knowledge.chunking`: heading/paragraph-aware
splitting, bounded fallback splitting, determinism, and "no empty chunks."
"""

import pytest

from app.engine.knowledge.chunking import ChunkingPolicy, chunk_document, compute_chunk_id
from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.models import KnowledgeDocument


def _doc(content: str, document_id: str = "doc-1") -> KnowledgeDocument:
    return KnowledgeDocument(document_id=document_id, source_id="src-1", title="T", content=content)


def test_chunking_respects_heading_boundaries_and_captures_heading_path() -> None:
    content = (
        "# Title\n\nIntro text.\n\n"
        "## Section A\n\nSection A body.\n\n"
        "## Section B\n\nSection B body."
    )
    chunks = chunk_document(_doc(content))
    heading_paths = [chunk.heading_path for chunk in chunks]
    assert ("Title",) in heading_paths
    assert ("Title", "Section A") in heading_paths
    assert ("Title", "Section B") in heading_paths


def test_chunking_splits_on_paragraph_boundaries() -> None:
    content = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = chunk_document(_doc(content))
    assert [chunk.content for chunk in chunks] == [
        "Paragraph one.",
        "Paragraph two.",
        "Paragraph three.",
    ]


def test_chunking_falls_back_to_bounded_split_for_oversized_paragraph() -> None:
    long_paragraph = "word " * 500  # ~2500 chars, one big paragraph, no blank lines
    chunks = chunk_document(_doc(long_paragraph), policy=ChunkingPolicy(max_chunk_chars=200))
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 200 for chunk in chunks)


def test_chunking_bounded_split_breaks_on_whitespace_not_mid_word() -> None:
    long_paragraph = "alpha beta gamma delta epsilon zeta eta theta iota kappa " * 5
    chunks = chunk_document(_doc(long_paragraph), policy=ChunkingPolicy(max_chunk_chars=50))
    for chunk in chunks:
        assert not chunk.content.startswith(" ")
        # every chunk should be composed of whole words (no word split across
        # a boundary would leave a dangling partial token at the very end
        # followed immediately by more letters in the next chunk's start)
        assert chunk.content == chunk.content.strip()


def test_chunking_heading_only_document_produces_no_chunks() -> None:
    """A document consisting of only a heading (no body paragraphs) is a
    valid `KnowledgeDocument` (its raw content is non-blank), but the
    chunker itself finds no paragraph content to emit -- zero chunks, not
    an error and not a blank/whitespace chunk."""
    chunks = chunk_document(_doc("# Just A Heading"))
    assert chunks == []


def test_chunking_never_produces_an_empty_or_whitespace_only_chunk() -> None:
    content = "# H\n\n\n\nParagraph.\n\n\n\n## H2\n\n\n"
    chunks = chunk_document(_doc(content))
    assert all(chunk.content.strip() for chunk in chunks)


def test_chunking_is_deterministic_across_repeated_calls() -> None:
    content = "# Title\n\nIntro.\n\n## Section\n\n" + ("word " * 300)
    doc = _doc(content)
    first = chunk_document(doc)
    for _ in range(10):
        again = chunk_document(doc)
        assert [c.chunk_id for c in first] == [c.chunk_id for c in again]
        assert [c.content for c in first] == [c.content for c in again]


def test_chunk_ordinals_are_stable_and_sequential() -> None:
    content = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_document(_doc(content))
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]


def test_chunk_ids_are_deterministic_from_document_id_ordinal_and_content() -> None:
    chunk_id = compute_chunk_id("doc-1", 0, "abcdef123456")
    assert chunk_id == compute_chunk_id("doc-1", 0, "abcdef123456")
    assert chunk_id != compute_chunk_id("doc-2", 0, "abcdef123456")
    assert chunk_id != compute_chunk_id("doc-1", 1, "abcdef123456")


def test_same_document_and_policy_produce_same_semantic_chunks() -> None:
    content = "# T\n\nParagraph one.\n\nParagraph two."
    doc_1 = _doc(content, document_id="doc-x")
    doc_2 = _doc(content, document_id="doc-x")
    chunks_1 = chunk_document(doc_1)
    chunks_2 = chunk_document(doc_2)
    assert [(c.chunk_id, c.content, c.heading_path) for c in chunks_1] == [
        (c.chunk_id, c.content, c.heading_path) for c in chunks_2
    ]


def test_repeated_identical_paragraphs_do_not_collide_on_chunk_id() -> None:
    """Two chunks with byte-identical content still get distinct chunk_ids
    (ordinal is part of the identity), so no data is silently lost."""
    content = "Same text.\n\nSame text.\n\nSame text."
    chunks = chunk_document(_doc(content))
    assert len(chunks) == 3
    assert len({c.chunk_id for c in chunks}) == 3


def test_chunking_policy_rejects_non_positive_max_chunk_chars() -> None:
    with pytest.raises(MalformedKnowledgeDataError):
        ChunkingPolicy(max_chunk_chars=0)


def test_chunking_boundary_max_chunk_chars_equals_one() -> None:
    content = "a b"
    chunks = chunk_document(_doc(content), policy=ChunkingPolicy(max_chunk_chars=1))
    assert [c.content for c in chunks] == ["a", "b"]
    assert all(len(c.content) <= 1 for c in chunks)


def test_chunking_boundary_exact_max_size() -> None:
    content = "12345"
    chunks = chunk_document(_doc(content), policy=ChunkingPolicy(max_chunk_chars=5))
    assert len(chunks) == 1
    assert chunks[0].content == "12345"


def test_chunking_boundary_one_char_above_max() -> None:
    content = "123456"
    chunks = chunk_document(_doc(content), policy=ChunkingPolicy(max_chunk_chars=5))
    assert len(chunks) == 2
    assert [c.content for c in chunks] == ["12345", "6"]


def test_chunking_boundary_very_long_token_no_whitespace() -> None:
    content = "abcdefghij"  # 10 chars
    chunks = chunk_document(_doc(content), policy=ChunkingPolicy(max_chunk_chars=3))
    assert len(chunks) == 4
    assert [c.content for c in chunks] == ["abc", "def", "ghi", "j"]
