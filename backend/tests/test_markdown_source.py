"""Tests for `app.integrations.markdown.source`: `MarkdownKnowledgeSource`,
`KnowledgeDocument` mapping, safe provenance, and the read-only guarantee."""

import hashlib
from pathlib import Path

import pytest

from app.integrations.markdown.errors import MarkdownSourceConfigError
from app.integrations.markdown.source import (
    MarkdownKnowledgeSource,
    MarkdownSourceConfig,
    build_document_id,
)


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _source(tmp_path: Path, source_id: str = "docs") -> MarkdownKnowledgeSource:
    return MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id=source_id))


# --- config validation -------------------------------------------------------------------


def test_blank_source_id_rejected() -> None:
    with pytest.raises(MarkdownSourceConfigError):
        MarkdownSourceConfig(root=".", source_id="  ")


def test_blank_source_kind_rejected() -> None:
    with pytest.raises(MarkdownSourceConfigError):
        MarkdownSourceConfig(root=".", source_id="docs", source_kind="")


# --- KnowledgeDocument mapping -------------------------------------------------------------


def test_list_documents_maps_notes_to_knowledge_documents(tmp_path: Path) -> None:
    _write(tmp_path, "architecture.md", "---\ntags: [core]\n---\n# Architecture\n\nOverview.\n")
    _write(tmp_path, "api.md", "# API\n\nEndpoints.\n")

    documents = _source(tmp_path).list_documents()

    assert len(documents) == 2
    by_id = {doc.document_id: doc for doc in documents}
    architecture = by_id[build_document_id("docs", "architecture.md")]
    assert architecture.title == "Architecture"
    assert architecture.source_id == "docs"
    assert "Overview." in architecture.content


def test_document_id_is_deterministic_source_relative(tmp_path: Path) -> None:
    _write(tmp_path, "sub/dir/note.md", "# T\n\nBody.\n")
    documents = _source(tmp_path, source_id="my-source").list_documents()
    assert documents[0].document_id == "my-source::sub/dir/note.md"


def test_repeated_scans_produce_identical_documents(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    source = _source(tmp_path)
    first = source.list_documents()
    second = source.list_documents()
    assert first == second


# --- safe, root-relative provenance -------------------------------------------------------


def test_metadata_never_contains_absolute_host_path(tmp_path: Path) -> None:
    _write(tmp_path, "notes/deep/file.md", "# T\n\nBody.\n")
    documents = _source(tmp_path).list_documents()
    document = documents[0]

    assert document.metadata["relative_path"] == "notes/deep/file.md"
    absolute_str = str(tmp_path)
    for value in document.metadata.values():
        assert absolute_str not in value
        assert "\\" not in value
    assert str(tmp_path) not in document.document_id
    assert str(tmp_path) not in document.title


def test_metadata_content_hash_matches_whole_file_hash(tmp_path: Path) -> None:
    content = "---\ntitle: T\n---\n# T\n\nBody.\n"
    _write(tmp_path, "a.md", content)
    document = _source(tmp_path).list_documents()[0]
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert document.metadata["content_hash"] == expected


def test_metadata_source_kind_is_markdown_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# T\n\nBody.\n")
    document = _source(tmp_path).list_documents()[0]
    assert document.metadata["source_kind"] == "markdown"


def test_tags_and_aliases_joined_into_safe_metadata_strings(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "---\ntags: [x, y]\naliases: [Z]\n---\n# T\n\nBody.\n")
    document = _source(tmp_path).list_documents()[0]
    assert document.metadata["tags"] == "x,y"
    assert document.metadata["aliases"] == "Z"


# --- failures don't crash list_documents ---------------------------------------------------


def test_empty_note_is_skipped_by_list_documents_not_raised(tmp_path: Path) -> None:
    _write(tmp_path, "empty.md", "---\ntitle: Only Frontmatter\n---\n\n")
    _write(tmp_path, "good.md", "# T\n\nBody.\n")

    documents = _source(tmp_path).list_documents()

    assert len(documents) == 1
    assert documents[0].title == "T"


def test_scan_reports_the_failure_list_documents_hides(tmp_path: Path) -> None:
    _write(tmp_path, "empty.md", "---\ntitle: Only Frontmatter\n---\n\n")

    scan_result = _source(tmp_path).scan()

    assert scan_result.notes == ()
    assert len(scan_result.failures) == 1


def test_unsafe_frontmatter_value_is_isolated_as_a_failure_not_a_crash(tmp_path: Path) -> None:
    """A tag value that happens to look like an absolute filesystem path
    is rejected by Stage 6A's own `KnowledgeDocument` safety validation --
    that must surface as one isolated `NoteFailure`, never an exception
    that aborts scanning/listing every other note in the source."""
    _write(tmp_path, "bad.md", "---\ntags: ['/etc/passwd']\n---\n# Bad\n\nBody.\n")
    _write(tmp_path, "good.md", "# Good\n\nBody.\n")
    source = _source(tmp_path)

    documents = source.list_documents()
    assert len(documents) == 1
    assert documents[0].title == "Good"

    scan_result = source.scan()
    assert {note.relative_path for note in scan_result.notes} == {"good.md"}
    assert {f.relative_path for f in scan_result.failures} == {"bad.md"}


# --- read-only guarantee -------------------------------------------------------------------


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_scan_never_modifies_source_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "---\ntitle: A\ntags: [x]\n---\n# A\n\nBody.\n")
    _write(tmp_path, "sub/b.md", "# B\n\nOther body.\n")

    before = _tree_snapshot(tmp_path)
    source = _source(tmp_path)
    source.scan()
    source.list_documents()
    source.scan()
    after = _tree_snapshot(tmp_path)

    assert before == after


def test_scan_creates_no_new_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    before_names = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}

    _source(tmp_path).list_documents()

    after_names = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    assert before_names == after_names
