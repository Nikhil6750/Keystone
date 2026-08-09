"""Tests for `app.integrations.obsidian.graph.build_link_graph`: resolved
links, backlinks, and the whole-vault orchestration (Stage 6B, sections
11-12, 21)."""

from pathlib import Path

from app.integrations.markdown.models import MarkdownNote
from app.integrations.markdown.parser import parse_markdown_note
from app.integrations.obsidian.adapter import ObsidianVaultAdapter
from app.integrations.obsidian.graph import build_link_graph
from app.integrations.obsidian.models import (
    AmbiguousKnowledgeLink,
    KnowledgeBacklink,
    LinkMatchKind,
    ObsidianVaultConfig,
    ResolvedKnowledgeLink,
    UnresolvedKnowledgeLink,
)


def _note(relative_path: str, text: str) -> MarkdownNote:
    return parse_markdown_note(relative_path, text)


def test_resolved_wikilink_produces_backlink() -> None:
    notes = (
        _note("architecture.md", "# Architecture\n\nSee [[backend]].\n"),
        _note("backend.md", "# Backend\n\nDetails.\n"),
    )
    graph = build_link_graph(notes)

    assert len(graph.resolved) == 1
    resolved = graph.resolved[0]
    assert resolved.target_relative_path == "backend.md"
    assert resolved.match_kind == LinkMatchKind.EXACT_PATH

    assert graph.backlinks == (
        KnowledgeBacklink(
            target_relative_path="backend.md", source_relative_paths=("architecture.md",)
        ),
    )


def test_multiple_sources_backlinking_one_target_are_sorted() -> None:
    notes = (
        _note("architecture.md", "# Architecture\n\nSee [[backend]].\n"),
        _note("decisions.md", "# Decisions\n\nSee [[backend]].\n"),
        _note("backend.md", "# Backend\n\nDetails.\n"),
    )
    graph = build_link_graph(notes)

    backend_backlinks = next(b for b in graph.backlinks if b.target_relative_path == "backend.md")
    assert backend_backlinks.source_relative_paths == ("architecture.md", "decisions.md")


def test_unresolved_wikilink_produces_no_backlink() -> None:
    notes = (_note("a.md", "# A\n\nSee [[does-not-exist]].\n"),)
    graph = build_link_graph(notes)

    assert len(graph.unresolved) == 1
    assert isinstance(graph.unresolved[0], UnresolvedKnowledgeLink)
    assert graph.backlinks == ()


def test_ambiguous_wikilink_never_produces_a_backlink() -> None:
    notes = (
        _note("a/dup.md", "# Dup\n\nBody.\n"),
        _note("b/dup.md", "# Dup\n\nBody.\n"),
        _note("source.md", "# Source\n\nSee [[dup]].\n"),
    )
    graph = build_link_graph(notes)

    assert len(graph.ambiguous) == 1
    assert isinstance(graph.ambiguous[0], AmbiguousKnowledgeLink)
    assert graph.ambiguous[0].candidate_relative_paths == ("a/dup.md", "b/dup.md")
    assert graph.backlinks == ()


def test_generic_markdown_link_also_resolved_within_a_vault() -> None:
    notes = (
        _note("architecture.md", "# Architecture\n\nSee [API](api.md).\n"),
        _note("api.md", "# API\n\nDetails.\n"),
    )
    graph = build_link_graph(notes)

    assert len(graph.resolved) == 1
    assert graph.resolved[0].target_relative_path == "api.md"
    assert graph.resolved[0].link.is_wikilink is False


def test_heading_and_alias_wikilinks_resolve_to_the_same_target() -> None:
    notes = (
        _note("a.md", "# A\n\nSee [[backend#Overview|Backend Overview]].\n"),
        _note("backend.md", "# Backend\n\n## Overview\n\nDetails.\n"),
    )
    graph = build_link_graph(notes)

    assert len(graph.resolved) == 1
    resolved = graph.resolved[0]
    assert resolved.target_relative_path == "backend.md"
    assert resolved.link.heading == "Overview"
    assert resolved.link.alias == "Backend Overview"


def test_graph_never_written_back_into_notes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n\nSee [[b]].\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nDetails.\n", encoding="utf-8")
    before = {
        "a.md": (tmp_path / "a.md").read_bytes(),
        "b.md": (tmp_path / "b.md").read_bytes(),
    }

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    adapter.build_link_graph()

    after = {
        "a.md": (tmp_path / "a.md").read_bytes(),
        "b.md": (tmp_path / "b.md").read_bytes(),
    }
    assert before == after


def test_resolved_link_is_typed_not_a_dict() -> None:
    notes = (
        _note("a.md", "# A\n\nSee [[b]].\n"),
        _note("b.md", "# B\n\nDetails.\n"),
    )
    graph = build_link_graph(notes)
    assert isinstance(graph.resolved[0], ResolvedKnowledgeLink)
    assert not isinstance(graph.resolved[0], dict)
