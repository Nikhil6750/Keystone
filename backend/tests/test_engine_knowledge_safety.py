"""Cross-cutting SAFETY tests for the Stage 6A knowledge engine: no
reasoning-shaped or credential-shaped field anywhere in the module, and no
absolute local machine path is ever accepted into an identifier or
metadata value."""

import dataclasses

import pytest

from app.engine.knowledge.context import ContextBudget, ContextChunk, ContextResult
from app.engine.knowledge.errors import UnsafeKnowledgeDataError
from app.engine.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeProvenance,
    looks_like_unsafe_local_path,
)
from app.engine.knowledge.ranking import RankingWeights
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, KnowledgeSearchResult

_FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "access_token",
    "session_token",
    "chain_of_thought",
    "reasoning",
    "internal_thought",
    "hidden_prompt",
    "raw_prompt",
    "scratchpad",
    "quality",
    "intelligence",
)

_KNOWLEDGE_DATACLASSES = (
    KnowledgeDocument,
    KnowledgeChunk,
    KnowledgeProvenance,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ContextBudget,
    ContextChunk,
    ContextResult,
    RankingWeights,
)


def test_no_knowledge_dataclass_has_a_forbidden_field_name() -> None:
    offenders: list[str] = []
    for cls in _KNOWLEDGE_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


@pytest.mark.parametrize(
    "metadata",
    [
        {"chain_of_thought": "x"},
        {"hidden_reasoning": "x"},
        {"reasoning_trace": "x"},
        {"internal_reasoning": "x"},
        {"private_reasoning": "x"},
        {"raw_prompt": "x"},
        {"hidden_prompt": "x"},
        {"scratchpad": "x"},
    ],
)
def test_reasoning_shaped_metadata_keys_are_rejected(metadata: dict[str, str]) -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeDocument(
            document_id="doc-1", source_id="src-1", title="T", content="c", metadata=metadata
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"password": "x"},
        {"api_key": "x"},
        {"credential": "x"},
        {"aws-secret-key": "x"},  # separator normalization
        {"Access_Token": "x"},  # case normalization
    ],
)
def test_credential_shaped_metadata_keys_are_rejected(metadata: dict[str, str]) -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeChunk(
            chunk_id="c1",
            document_id="doc-1",
            source_id="src-1",
            content="content",
            ordinal=0,
            metadata=metadata,
        )


def test_benign_metadata_mentioning_reasoning_substring_is_accepted() -> None:
    """`reasoning_step_count` is a plain observable count, not reasoning
    content -- the safety check matches exact reserved key names, not any
    key merely containing the substring "reasoning" (shared behavior with
    `app.contracts.evidence_safety`)."""
    doc = KnowledgeDocument(
        document_id="doc-1",
        source_id="src-1",
        title="T",
        content="c",
        metadata={"reasoning_step_count": "4"},
    )
    assert doc.metadata == {"reasoning_step_count": "4"}


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/home/user/vault/notes.md",
        r"C:\Users\dev\vault\notes.md",
        "c:/Users/dev/vault/notes.md",
        r"\\fileserver\share\notes.md",
        "vault/../../../etc/passwd",
    ],
)
def test_looks_like_unsafe_local_path_detects_absolute_and_traversal_paths(
    unsafe_path: str,
) -> None:
    assert looks_like_unsafe_local_path(unsafe_path) is True


@pytest.mark.parametrize(
    "safe_value",
    ["org/repo", "notes/my-note", "a1b2c3d4", "Some Title With Spaces"],
)
def test_looks_like_unsafe_local_path_accepts_ordinary_identifiers(safe_value: str) -> None:
    assert looks_like_unsafe_local_path(safe_value) is False


def test_no_absolute_path_survives_into_indexed_chunk_metadata() -> None:
    """An unsafe metadata value can never reach the index through the full
    document -> chunk -> index pipeline, because it can never construct a
    `KnowledgeDocument` in the first place -- the whole pipeline never
    starts."""
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeDocument(
            document_id="doc-1",
            source_id="src-1",
            title="T",
            content="Real content here.",
            metadata={"origin_path": "/home/user/private/vault"},
        )


def test_search_request_metadata_filters_are_also_safety_validated() -> None:
    with pytest.raises(UnsafeKnowledgeDataError):
        KnowledgeSearchRequest(query="x", metadata_filters={"api_key": "leak"})
