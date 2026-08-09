"""Portability tests (Stage 6B, section 20): the generic Markdown source
works unchanged across a plain Markdown folder, a Git documentation tree,
and a Foam-style workspace -- with no Obsidian-specific assumption
anywhere. `test_obsidian_adapter.py` covers the Obsidian case."""

from pathlib import Path

from app.integrations.markdown.source import MarkdownKnowledgeSource, MarkdownSourceConfig


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_plain_markdown_folder(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "architecture.md", "# Architecture\n\nOverview.\n")
    _write(docs, "api.md", "# API\n\nEndpoints.\n")
    _write(docs, "decisions.md", "# Decisions\n\nWhy we chose X.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=docs, source_id="docs"))
    documents = source.list_documents()

    assert {doc.title for doc in documents} == {"Architecture", "API", "Decisions"}


def test_git_documentation_tree_with_dot_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo, "README.md", "# My Project\n\nWelcome.\n")
    _write(repo, "docs/CONTRIBUTING.md", "# Contributing\n\nGuidelines.\n")
    # A realistic `.git` internal tree -- must never be scanned.
    _write(repo, ".git/refs/heads/main", "abc123")
    _write(repo, ".git/config", "[core]\n")
    _write(repo, ".git/hooks/pre-commit.md", "# Fake hook doc\n\nShould not be indexed.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=repo, source_id="repo-docs"))
    documents = source.list_documents()

    titles = {doc.title for doc in documents}
    assert titles == {"My Project", "Contributing"}


def test_foam_style_workspace_no_dot_obsidian_required(tmp_path: Path) -> None:
    """Foam is a plain-Markdown, VS Code-based note-taking workflow: no
    special hidden directory, wiki-link-like `[[note]]` references are
    just represented as ordinary text by the generic parser (Foam itself
    renders them via a VS Code extension, not via any file-format
    requirement Stage 6B needs to special-case)."""
    workspace = tmp_path / "foam-workspace"
    _write(workspace, "inbox.md", "# Inbox\n\nQuick capture note.\n")
    _write(workspace, "projects/keystone.md", "---\ntags: [project]\n---\n# Keystone\n\nNotes.\n")
    _write(workspace, ".vscode/settings.json", "{}")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=workspace, source_id="foam"))
    documents = source.list_documents()

    assert {doc.title for doc in documents} == {"Inbox", "Keystone"}
    keystone = next(doc for doc in documents if doc.title == "Keystone")
    assert keystone.metadata["tags"] == "project"


def test_no_dot_obsidian_folder_required_for_generic_source(tmp_path: Path) -> None:
    docs = tmp_path / "plain"
    _write(docs, "note.md", "# Note\n\nNo vault structure at all.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=docs, source_id="plain"))
    assert len(source.list_documents()) == 1
