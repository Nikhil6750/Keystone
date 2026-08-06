"""Tests for the Obsidian knowledge contracts."""

from datetime import UTC, datetime

from app.contracts.knowledge import KnowledgeDocument, KnowledgeSearchResult


def test_document_uses_opaque_id_and_relative_path() -> None:
    document = KnowledgeDocument.model_validate(
        {
            "document_id": "doc-abc123",
            "vault_id": "vault-1",
            "title": "Notes on routing",
            "relative_path": "projects/keystone/routing.md",
            "content_hash": "deadbeef",
            "size_bytes": 512,
            "modified_at": datetime.now(UTC),
        }
    )
    assert document.document_id == "doc-abc123"
    assert not document.relative_path.startswith(("/", "C:", "\\"))


def test_document_defaults_are_empty_collections() -> None:
    document = KnowledgeDocument.model_validate(
        {
            "document_id": "doc-1",
            "vault_id": "vault-1",
            "title": "Empty",
            "relative_path": "empty.md",
            "content_hash": "abc",
            "size_bytes": 0,
            "modified_at": datetime.now(UTC),
        }
    )
    assert document.tags == []
    assert document.links == []
    assert document.backlinks == []


def test_search_result_carries_a_score_and_snippet() -> None:
    result = KnowledgeSearchResult.model_validate(
        {
            "document_id": "doc-1",
            "vault_id": "vault-1",
            "title": "Routing notes",
            "snippet": "...evidence-based routing...",
            "score": 0.83,
        }
    )
    assert result.score == 0.83
    assert result.snippet != ""
