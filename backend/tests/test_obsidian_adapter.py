"""Tests for `app.integrations.obsidian.adapter.ObsidianVaultAdapter`:
`.obsidian/**` exclusion, `KnowledgeSource` protocol conformance, and
delegation to `MarkdownKnowledgeSource` (no reimplementation)."""

from pathlib import Path

from app.integrations.obsidian.adapter import ObsidianVaultAdapter
from app.integrations.obsidian.models import ObsidianVaultConfig


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_obsidian_dir_excluded_from_scanning(tmp_path: Path) -> None:
    _write(tmp_path, "architecture.md", "# Architecture\n\nBody.\n")
    _write(tmp_path, ".obsidian/plugins/some-plugin/data.md", "# Should not be indexed\n\nX.\n")
    _write(tmp_path, ".obsidian/workspace.md", "# Also excluded\n\nX.\n")

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    documents = adapter.list_documents()

    assert len(documents) == 1
    assert documents[0].title == "Architecture"


def test_source_kind_is_obsidian(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    document = adapter.list_documents()[0]
    assert document.metadata["source_kind"] == "obsidian"


def test_adapter_satisfies_knowledge_source_protocol(tmp_path: Path) -> None:
    from app.engine.knowledge.source import KnowledgeSource

    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))

    knowledge_source: KnowledgeSource = adapter
    assert knowledge_source.source_id == "vault"
    assert len(knowledge_source.list_documents()) == 1


def test_adapter_exposes_underlying_markdown_source_for_sync(tmp_path: Path) -> None:
    from app.engine.knowledge.index import KnowledgeIndex
    from app.integrations.markdown.state import InMemoryKnowledgeSourceStateRepository
    from app.integrations.markdown.sync import sync_source

    _write(tmp_path, "a.md", "# A\n\nBody.\n")
    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()

    result = sync_source(adapter.markdown_source, index, state)

    assert {e.relative_path for e in result.added} == {"a.md"}
    assert index.stats().document_count == 1


def test_extra_excluded_dirs_still_honored(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md", "# Kept\n\nBody.\n")
    _write(tmp_path, "templates/ignored.md", "# Ignored\n\nBody.\n")

    adapter = ObsidianVaultAdapter(
        ObsidianVaultConfig(
            root=tmp_path, source_id="vault", extra_excluded_dir_names=frozenset({"templates"})
        )
    )
    documents = adapter.list_documents()

    assert len(documents) == 1
    assert documents[0].title == "Kept"


def test_scan_never_modifies_vault_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# A\n\n[[b]]\n")
    _write(tmp_path, "b.md", "# B\n\nBody.\n")
    _write(tmp_path, ".obsidian/config.json", "{}")

    before = {
        p.relative_to(tmp_path): p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()
    }

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    adapter.list_documents()
    adapter.build_link_graph()

    after = {
        p.relative_to(tmp_path): p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()
    }
    assert before == after
