"""Tests for `app.integrations.markdown.sync.sync_source`: incremental
diffing (added/updated/deleted/unchanged/failed), rename handling, and the
storage-neutral state repository."""

from pathlib import Path

from app.engine.knowledge.index import KnowledgeIndex
from app.integrations.markdown.source import MarkdownKnowledgeSource, MarkdownSourceConfig
from app.integrations.markdown.state import InMemoryKnowledgeSourceStateRepository
from app.integrations.markdown.sync import sync_source


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _source(tmp_path: Path, source_id: str = "docs") -> MarkdownKnowledgeSource:
    return MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id=source_id))


def test_first_sync_reports_everything_as_added(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    _write(tmp_path, "b.md", "# B\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()

    result = sync_source(_source(tmp_path), index, state)

    assert {e.relative_path for e in result.added} == {"a.md", "b.md"}
    assert result.updated == ()
    assert result.deleted == ()
    assert result.unchanged == ()
    assert result.failed == ()
    assert index.stats().document_count == 2


def test_second_sync_with_no_changes_is_all_unchanged(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)

    sync_source(source, index, state)
    result = sync_source(source, index, state)

    assert result.added == ()
    assert result.updated == ()
    assert {e.relative_path for e in result.unchanged} == {"a.md"}
    assert index.stats().document_count == 1


def test_modified_note_is_reported_as_updated_and_reindexed(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nOriginal body.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)
    sync_source(source, index, state)

    _write(tmp_path, "a.md", "# A\n\nChanged body entirely.\n")
    result = sync_source(source, index, state)

    assert {e.relative_path for e in result.updated} == {"a.md"}
    assert result.added == ()
    document_id = result.updated[0].document_id
    document = index.get_document(document_id)
    assert document is not None
    assert "Changed body entirely." in document.content


def test_deleted_note_is_removed_from_index(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    _write(tmp_path, "b.md", "# B\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)
    sync_source(source, index, state)

    (tmp_path / "b.md").unlink()
    result = sync_source(source, index, state)

    assert {e.relative_path for e in result.deleted} == {"b.md"}
    assert index.stats().document_count == 1
    assert index.list_documents()[0].document_id.endswith("a.md")


def test_rename_is_old_deleted_and_new_added(tmp_path: Path) -> None:
    _write(tmp_path, "old-name.md", "# T\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)
    sync_source(source, index, state)

    (tmp_path / "old-name.md").rename(tmp_path / "new-name.md")
    result = sync_source(source, index, state)

    assert {e.relative_path for e in result.deleted} == {"old-name.md"}
    assert {e.relative_path for e in result.added} == {"new-name.md"}
    assert index.stats().document_count == 1


def test_unchanged_content_different_mtime_is_still_unchanged(tmp_path: Path) -> None:
    content = "# A\n\nBody.\n"
    path = _write(tmp_path, "a.md", content)
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)
    sync_source(source, index, state)

    # Rewrite identical bytes -- mtime changes, content does not.
    path.write_text(content, encoding="utf-8")
    result = sync_source(source, index, state)

    assert result.updated == ()
    assert {e.relative_path for e in result.unchanged} == {"a.md"}


def test_failed_note_is_reported_and_leaves_prior_state_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.md", "# A\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)
    sync_source(source, index, state)
    previous_document_id = index.list_documents()[0].document_id

    path.write_text("---\ntitle: Only Frontmatter\n---\n\n", encoding="utf-8")
    result = sync_source(source, index, state)

    assert len(result.failed) == 1
    assert result.failed[0].relative_path == "a.md"
    assert result.deleted == ()
    assert result.updated == ()
    # The previously-good document is left exactly as it was.
    assert index.get_document(previous_document_id) is not None


def test_first_failure_then_fix_reports_added(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.md", "---\ntitle: Only Frontmatter\n---\n\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)

    first = sync_source(source, index, state)
    assert first.added == ()
    assert len(first.failed) == 1

    path.write_text("# Fixed\n\nNow has a body.\n", encoding="utf-8")
    second = sync_source(source, index, state)

    assert {e.relative_path for e in second.added} == {"a.md"}
    assert second.failed == ()


def test_sync_is_idempotent_state_unchanged_by_repeated_unchanged_sync(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    source = _source(tmp_path)

    sync_source(source, index, state)
    state_after_first = state.get_state("docs")
    sync_source(source, index, state)
    state_after_second = state.get_state("docs")

    assert state_after_first == state_after_second


def test_multiple_sources_have_independent_state(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    other_root = tmp_path / "other"
    docs_root.mkdir()
    other_root.mkdir()
    _write(docs_root, "a.md", "# A\n\nBody.\n")
    _write(other_root, "a.md", "# A\n\nDifferent body entirely.\n")

    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()
    docs_source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=docs_root, source_id="docs"))
    other_source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=other_root, source_id="other"))

    sync_source(docs_source, index, state)
    sync_source(other_source, index, state)

    assert index.stats().document_count == 2
    assert set(index.stats().source_ids) == {"docs", "other"}


# --- state repository ------------------------------------------------------------------


def test_in_memory_state_repository_returns_empty_for_unknown_source() -> None:
    state = InMemoryKnowledgeSourceStateRepository()
    assert state.get_state("never-synced") == {}


def test_in_memory_state_repository_save_and_get_round_trips() -> None:
    from app.integrations.markdown.state import DocumentSyncState

    state = InMemoryKnowledgeSourceStateRepository()
    saved = {
        "a.md": DocumentSyncState(relative_path="a.md", document_id="docs::a.md", content_hash="h")
    }
    state.save_state("docs", saved)

    assert state.get_state("docs") == saved


def test_in_memory_state_repository_get_returns_a_copy() -> None:
    from app.integrations.markdown.state import DocumentSyncState

    state = InMemoryKnowledgeSourceStateRepository()
    state.save_state(
        "docs",
        {"a.md": DocumentSyncState(relative_path="a.md", document_id="d", content_hash="h")},
    )
    snapshot = state.get_state("docs")
    snapshot["b.md"] = DocumentSyncState(relative_path="b.md", document_id="d2", content_hash="h2")

    assert "b.md" not in state.get_state("docs")
