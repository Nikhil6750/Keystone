"""Tests for `app.engine.knowledge.models` (`KnowledgeDocument`,
`KnowledgeChunk`, `KnowledgeProvenance`) and `app.engine.knowledge.source`
(`InMemoryKnowledgeSource`): valid construction, deterministic identity,
and safe-metadata validation."""

import pytest

from app.engine.knowledge.errors import MalformedKnowledgeDataError, UnsafeKnowledgeDataError
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeProvenance
from app.engine.knowledge.source import InMemoryKnowledgeSource

# --- KnowledgeDocument -----------------------------------------------------------------


def test_valid_document_constructs() -> None:
    doc = KnowledgeDocument(
        document_id="doc-1",
        source_id="src-1",
        title="Overview",
        content="Some real content here.",
        metadata={"category": "reference"},
    )
    assert doc.document_id == "doc-1"
    assert doc.metadata == {"category": "reference"}


def test_document_identity_is_deterministic_content_hash() -> None:
    doc_a = KnowledgeDocument(
        document_id="doc-1", source_id="src-1", title="T", content="Hello world"
    )
    doc_b = KnowledgeDocument(
        document_id="doc-2", source_id="src-1", title="T2", content="Hello world"
    )
    assert (
        doc_a.content_hash == doc_b.content_hash
    )  # same content -> same hash, regardless of id/title

    doc_c = KnowledgeDocument(
        document_id="doc-1", source_id="src-1", title="T", content="Different"
    )
    assert doc_a.content_hash != doc_c.content_hash


def test_document_content_hash_cannot_be_supplied_by_caller() -> None:
    """`content_hash` is `init=False` -- always computed, never trusted
    from caller input, so it can never lie about the document's content."""
    with pytest.raises(TypeError):
        KnowledgeDocument(  # type: ignore[call-arg]
            document_id="doc-1",
            source_id="src-1",
            title="T",
            content="c",
            content_hash="not-a-real-hash",
        )


@pytest.mark.parametrize("field_name", ["document_id", "source_id", "title", "content"])
def test_blank_required_fields_are_rejected(field_name: str) -> None:
    kwargs = {
        "document_id": "doc-1",
        "source_id": "src-1",
        "title": "T",
        "content": "c",
    }
    kwargs[field_name] = "   "
    with pytest.raises(MalformedKnowledgeDataError):
        KnowledgeDocument(**kwargs)  # type: ignore[arg-type]


def test_safe_metadata_is_accepted() -> None:
    doc = KnowledgeDocument(
        document_id="doc-1",
        source_id="src-1",
        title="T",
        content="c",
        metadata={"category": "notes", "language": "en"},
    )
    assert doc.metadata["category"] == "notes"


@pytest.mark.parametrize(
    "metadata",
    [
        {"chain_of_thought": "secret reasoning"},
        {"hidden_reasoning": "secret"},
        {"api_key": "sk-12345"},
        {"password": "hunter2"},
        {"aws_secret_key": "xyz"},
        {"access_token": "abc"},
    ],
)
def test_unsafe_metadata_keys_are_rejected(metadata: dict[str, str]) -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeDocument(
            document_id="doc-1", source_id="src-1", title="T", content="c", metadata=metadata
        )


@pytest.mark.parametrize(
    "unsafe_value",
    ["/etc/passwd", r"C:\Users\dev\secret", "c:/Users/dev/secret", r"\\server\share"],
)
def test_unsafe_metadata_values_are_rejected(unsafe_value: str) -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeDocument(
            document_id="doc-1",
            source_id="src-1",
            title="T",
            content="c",
            metadata={"origin": unsafe_value},
        )


def test_document_id_rejects_absolute_path_shape() -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeDocument(document_id="/etc/passwd", source_id="src-1", title="T", content="c")


# --- KnowledgeChunk ------------------------------------------------------------------------


def test_valid_chunk_constructs() -> None:
    chunk = KnowledgeChunk(
        chunk_id="doc-1::chunk::0::abc",
        document_id="doc-1",
        source_id="src-1",
        content="chunk content",
        ordinal=0,
        heading_path=("Intro",),
    )
    assert chunk.ordinal == 0
    assert chunk.content_hash


def test_chunk_rejects_blank_content() -> None:
    with pytest.raises(MalformedKnowledgeDataError):
        KnowledgeChunk(
            chunk_id="c1", document_id="doc-1", source_id="src-1", content="   ", ordinal=0
        )


def test_chunk_rejects_negative_ordinal() -> None:
    with pytest.raises(MalformedKnowledgeDataError):
        KnowledgeChunk(
            chunk_id="c1", document_id="doc-1", source_id="src-1", content="c", ordinal=-1
        )


def test_chunk_metadata_is_validated_same_as_document_metadata() -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeChunk(
            chunk_id="c1",
            document_id="doc-1",
            source_id="src-1",
            content="c",
            ordinal=0,
            metadata={"secret": "value"},
        )


# --- KnowledgeProvenance ---------------------------------------------------------------------


def test_provenance_carries_full_identity_chain() -> None:
    provenance = KnowledgeProvenance(
        source_id="src-1",
        document_id="doc-1",
        chunk_id="c1",
        heading_path=("Intro",),
        rank=1,
        score=0.5,
    )
    assert (provenance.source_id, provenance.document_id, provenance.chunk_id) == (
        "src-1",
        "doc-1",
        "c1",
    )


# --- InMemoryKnowledgeSource -----------------------------------------------------------------


def test_in_memory_source_lists_its_documents() -> None:
    doc = KnowledgeDocument(document_id="doc-1", source_id="src-1", title="T", content="c")
    source = InMemoryKnowledgeSource(source_id="src-1", documents=(doc,))
    assert source.list_documents() == [doc]


def test_in_memory_source_rejects_mismatched_document_source_id() -> None:
    doc = KnowledgeDocument(document_id="doc-1", source_id="other-src", title="T", content="c")
    with pytest.raises(ValueError, match="source_id"):
        InMemoryKnowledgeSource(source_id="src-1", documents=(doc,))


def test_in_memory_source_rejects_blank_source_id() -> None:
    with pytest.raises(ValueError):
        InMemoryKnowledgeSource(source_id="  ")
