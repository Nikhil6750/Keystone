"""Security adversarial tests (Stage 6B, sections 22-23): path traversal,
symlink escape, absolute/`file://`/web links, `.obsidian`/`.git`/
`node_modules` exclusion, binary files, malformed YAML, embedded HTML/code
-- none may lead to code execution or an outside-root read, and no
absolute host path may ever appear in any public output."""

import os
from pathlib import Path

import pytest

from app.engine.knowledge.index import KnowledgeIndex
from app.integrations.markdown.errors import PathSafetyError
from app.integrations.markdown.parser import parse_markdown_note
from app.integrations.markdown.scanner import resolve_relative_path, resolve_root
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


# --- path traversal / outside-root reads ------------------------------------------------


def test_relative_path_traversal_rejected(tmp_path: Path) -> None:
    root = resolve_root(tmp_path)
    with pytest.raises(PathSafetyError):
        resolve_relative_path(root, "../../../secret.md")


def test_absolute_markdown_link_target_never_fetched_or_resolved(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-abs-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.md").write_text("# Secret\n\nTop secret.\n", encoding="utf-8")

    vault = tmp_path / "vault"
    absolute_target = (outside / "secret.md").as_posix()
    _write(vault, "a.md", f"# A\n\n[Secret]({absolute_target})\n")

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=vault, source_id="v"))
    graph = adapter.build_link_graph()

    # An absolute path (drive-letter or leading slash) is classified as an
    # external-style target and is never a resolution candidate -- it can
    # never appear as `resolved`, and the outside file is never opened
    # (its content never appears in any indexed document).
    assert graph.resolved == ()
    documents = adapter.list_documents()
    assert all("Top secret" not in doc.content for doc in documents)


@pytest.mark.parametrize(
    "target",
    ["file:///etc/passwd", "https://evil.example.com/exfiltrate", "http://example.com"],
)
def test_file_and_web_url_links_never_followed(tmp_path: Path, target: str) -> None:
    _write(tmp_path, "a.md", f"# A\n\n[Link]({target})\n")
    note = parse_markdown_note("a.md", (tmp_path / "a.md").read_text(encoding="utf-8"))
    assert note.links[0].target == target
    # Representation only -- nothing in this package performs network or
    # arbitrary-filesystem I/O based on a link target.


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_symlink_escape_never_read(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-sym-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.md").write_text("# Secret\n\nShould never appear.\n", encoding="utf-8")

    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "kept.md", "# Kept\n\nFine.\n")
    try:
        os.symlink(outside / "secret.md", vault / "escape.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=vault, source_id="v"))
    documents = source.list_documents()

    assert all("Secret" not in doc.content for doc in documents)
    assert all("Should never appear" not in doc.content for doc in documents)


# --- exclusion of sensitive directories/files --------------------------------------------


def test_obsidian_git_and_node_modules_excluded_together(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md", "# Kept\n\nBody.\n")
    _write(tmp_path, ".obsidian/plugins/x/data.md", "# Plugin\n\nX.\n")
    _write(tmp_path, ".git/COMMIT_EDITMSG", "secret commit message")
    _write(tmp_path, "node_modules/pkg/README.md", "# Package\n\nX.\n")

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="v"))
    documents = adapter.list_documents()

    assert len(documents) == 1
    assert documents[0].title == "Kept"


def test_env_and_key_files_never_indexed_even_if_readable(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md", "# Kept\n\nBody.\n")
    (tmp_path / ".env").write_text("API_KEY=super-secret", encoding="utf-8")
    (tmp_path / "private.key").write_text("-----BEGIN RSA PRIVATE KEY-----", encoding="utf-8")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    documents = source.list_documents()

    assert len(documents) == 1
    assert all("super-secret" not in doc.content for doc in documents)


def test_binary_file_disguised_with_md_extension_does_not_crash_or_execute(
    tmp_path: Path,
) -> None:
    binary_path = tmp_path / "corrupt.md"
    binary_path.write_bytes(bytes(range(256)))
    _write(tmp_path, "good.md", "# Good\n\nBody.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    scan_result = source.scan()

    # Never crashes; the undecodable file is reported as a failure, the
    # good file still indexes normally.
    assert any(f.relative_path == "corrupt.md" for f in scan_result.failures)
    assert any(note.relative_path == "good.md" for note in scan_result.notes)


# --- malformed YAML / embedded HTML / code blocks -----------------------------------------


def test_malformed_yaml_never_crashes_or_executes(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "---\ntitle: [unterminated list\n---\n# A\n\nBody.\n")
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    documents = source.list_documents()
    assert len(documents) == 1


def test_yaml_unsafe_tag_cannot_construct_python_objects(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        '---\nx: !!python/object/apply:os.system ["echo pwned"]\n---\n# A\n\nBody.\n',
    )
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    # yaml.safe_load refuses the unsafe tag and raises -- caught and
    # degraded to empty frontmatter, never executed, never re-raised.
    documents = source.list_documents()
    assert len(documents) == 1
    assert documents[0].metadata["tags"] == ""


def test_embedded_html_and_js_never_executed_just_stored_as_text(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "# A\n\n<script>alert('xss')</script>\n\n<img src=x onerror=alert(1)>\n",
    )
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    documents = source.list_documents()
    assert len(documents) == 1
    assert "<script>" in documents[0].content  # stored as inert text, never executed


def test_code_blocks_never_executed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "# A\n\n```python\nimport os\nos.system('rm -rf /')\n```\n",
    )
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="v"))
    documents = source.list_documents()
    assert len(documents) == 1  # parsed as inert text; nothing executed


# --- no absolute host path ever leaks -----------------------------------------------------


def test_no_absolute_path_in_documents_metadata_or_sync_results(tmp_path: Path) -> None:
    private_root = tmp_path / "Users" / "PrivatePerson" / "SecretProject" / "vault"
    _write(private_root, "notes/secret-plan.md", "# Secret Plan\n\nConfidential.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=private_root, source_id="v"))
    index = KnowledgeIndex()
    state = InMemoryKnowledgeSourceStateRepository()

    documents = source.list_documents()
    sync_result = sync_source(source, index, state)

    sensitive_fragments = ["PrivatePerson", "SecretProject", str(private_root)]

    for document in documents:
        for fragment in sensitive_fragments:
            assert fragment not in document.document_id
            assert fragment not in document.title
            for value in document.metadata.values():
                assert fragment not in value

    for entry in (*sync_result.added, *sync_result.updated, *sync_result.unchanged):
        for fragment in sensitive_fragments:
            assert fragment not in entry.relative_path
            assert fragment not in entry.document_id


def test_no_absolute_path_in_obsidian_link_graph(tmp_path: Path) -> None:
    private_root = tmp_path / "Users" / "PrivatePerson" / "SecretProject" / "vault"
    _write(private_root, "a.md", "# A\n\nSee [[b]].\n")
    _write(private_root, "b.md", "# B\n\nBody.\n")

    graph = ObsidianVaultAdapter(
        ObsidianVaultConfig(root=private_root, source_id="v")
    ).build_link_graph()

    for resolved in graph.resolved:
        assert "PrivatePerson" not in resolved.target_relative_path
        assert "PrivatePerson" not in resolved.link.source_relative_path
    for backlink in graph.backlinks:
        assert "PrivatePerson" not in backlink.target_relative_path
        for source in backlink.source_relative_paths:
            assert "PrivatePerson" not in source


def test_error_messages_never_include_absolute_host_path(tmp_path: Path) -> None:
    private_root = tmp_path / "Users" / "PrivatePerson" / "SecretProject" / "vault"
    private_root.mkdir(parents=True)
    root = resolve_root(private_root)

    with pytest.raises(PathSafetyError) as exc_info:
        resolve_relative_path(root, "../outside.md")

    assert "PrivatePerson" not in str(exc_info.value)
    assert "SecretProject" not in str(exc_info.value)
