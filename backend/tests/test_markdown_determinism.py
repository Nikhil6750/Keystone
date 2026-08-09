"""Determinism tests (Stage 6B, section 24): the same source tree, no
matter the filesystem creation order, always produces the same documents,
hashes, sync results, and (for a vault) the same link graph."""

import random
from pathlib import Path

from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.integrations.markdown.source import MarkdownKnowledgeSource, MarkdownSourceConfig
from app.integrations.markdown.state import InMemoryKnowledgeSourceStateRepository
from app.integrations.markdown.sync import sync_source
from app.integrations.obsidian.adapter import ObsidianVaultAdapter
from app.integrations.obsidian.models import ObsidianVaultConfig


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _semantic_documents(documents: list[KnowledgeDocument]) -> list[tuple[object, ...]]:
    """Documents compared on everything except `modified_at`/`created_at`
    -- mtime legitimately differs between two independently-written trees
    of otherwise-identical content (Stage 6B section 7: mtime is
    operational metadata only, never semantic identity), so a
    determinism check must not require it to match."""
    return [
        (doc.document_id, doc.source_id, doc.title, doc.content, doc.metadata, doc.content_hash)
        for doc in sorted(documents, key=lambda d: d.document_id)
    ]


_FILES = {
    "architecture.md": "---\ntags: [core, design]\n---\n# Architecture\n\nSee [API](api.md).\n",
    "api.md": "# API\n\nSee [[architecture]] and [[Backend|Backend Notes]].\n",
    "backend.md": "---\naliases: [Backend Notes]\n---\n# Backend\n\nDetails.\n",
    "notes/decisions.md": "# Decisions\n\n[[unknown-note]]\n",
    "notes/random.md": "## Random\n\nSome more content for good measure.\n",
}


def test_repeated_scan_of_unchanged_tree_yields_identical_documents(tmp_path: Path) -> None:
    for relative_path, content in _FILES.items():
        _write(tmp_path, relative_path, content)
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="docs"))

    baseline = source.list_documents()
    for _ in range(10):
        assert source.list_documents() == baseline


def test_scan_order_independent_of_filesystem_creation_order(tmp_path: Path) -> None:
    items = list(_FILES.items())
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    for relative_path, content in items:
        _write(baseline_root, relative_path, content)
    baseline_docs = MarkdownKnowledgeSource(
        MarkdownSourceConfig(root=baseline_root, source_id="docs")
    ).list_documents()

    rng = random.Random(1234)
    for trial in range(5):
        shuffled_root = tmp_path / f"trial-{trial}"
        shuffled_root.mkdir()
        shuffled_items = items[:]
        rng.shuffle(shuffled_items)
        for relative_path, content in shuffled_items:
            _write(shuffled_root, relative_path, content)
        docs = MarkdownKnowledgeSource(
            MarkdownSourceConfig(root=shuffled_root, source_id="docs")
        ).list_documents()
        assert _semantic_documents(docs) == _semantic_documents(baseline_docs)


def test_repeated_sync_of_unchanged_tree_is_idempotent(tmp_path: Path) -> None:
    for relative_path, content in _FILES.items():
        _write(tmp_path, relative_path, content)
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="docs"))
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()

    first = sync_source(source, index, state)
    assert {e.relative_path for e in first.added} == set(_FILES)

    for _ in range(10):
        result = sync_source(source, index, state)
        assert result.added == ()
        assert result.updated == ()
        assert result.deleted == ()
        assert {e.relative_path for e in result.unchanged} == set(_FILES)
    assert index.stats().document_count == len(_FILES)


def test_vault_link_graph_deterministic_across_repeated_builds_and_shuffled_order(
    tmp_path: Path,
) -> None:
    items = list(_FILES.items())
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    for relative_path, content in items:
        _write(baseline_root, relative_path, content)
    baseline_graph = ObsidianVaultAdapter(
        ObsidianVaultConfig(root=baseline_root, source_id="vault")
    ).build_link_graph()

    for _ in range(10):
        graph = ObsidianVaultAdapter(
            ObsidianVaultConfig(root=baseline_root, source_id="vault")
        ).build_link_graph()
        assert graph == baseline_graph

    rng = random.Random(99)
    for trial in range(3):
        shuffled_root = tmp_path / f"vault-trial-{trial}"
        shuffled_root.mkdir()
        shuffled_items = items[:]
        rng.shuffle(shuffled_items)
        for relative_path, content in shuffled_items:
            _write(shuffled_root, relative_path, content)
        graph = ObsidianVaultAdapter(
            ObsidianVaultConfig(root=shuffled_root, source_id="vault")
        ).build_link_graph()
        assert graph == baseline_graph
