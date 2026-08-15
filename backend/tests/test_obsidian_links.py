"""Tests for `app.integrations.obsidian.links`: exact-path-wins
resolution, filename/alias matching, and ambiguity (Stage 6B, section
11)."""

from app.integrations.obsidian.links import resolve_link
from app.integrations.obsidian.models import (
    AmbiguousKnowledgeLink,
    KnowledgeLink,
    LinkMatchKind,
    ResolvedKnowledgeLink,
    UnresolvedKnowledgeLink,
)


def _link(target: str, *, is_wikilink: bool = True) -> KnowledgeLink:
    return KnowledgeLink(
        source_relative_path="source.md", target_text=target, is_wikilink=is_wikilink
    )


def test_exact_relative_path_match_wins() -> None:
    known = frozenset({"architecture.md", "folder/architecture.md"})
    outcome = resolve_link(_link("folder/architecture"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, ResolvedKnowledgeLink)
    assert outcome.target_relative_path == "folder/architecture.md"
    assert outcome.match_kind == LinkMatchKind.EXACT_PATH


def test_exact_path_wins_even_when_a_same_named_file_exists_elsewhere() -> None:
    known = frozenset({"a/note.md", "b/note.md"})
    outcome = resolve_link(_link("a/note"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, ResolvedKnowledgeLink)
    assert outcome.target_relative_path == "a/note.md"
    assert outcome.match_kind == LinkMatchKind.EXACT_PATH


def test_filename_match_when_unique() -> None:
    known = frozenset({"deep/nested/architecture.md"})
    outcome = resolve_link(_link("architecture"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, ResolvedKnowledgeLink)
    assert outcome.target_relative_path == "deep/nested/architecture.md"
    assert outcome.match_kind == LinkMatchKind.FILENAME


def test_ambiguous_filename_match_across_folders() -> None:
    known = frozenset({"a/note.md", "b/note.md"})
    outcome = resolve_link(_link("note"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, AmbiguousKnowledgeLink)
    assert outcome.candidate_relative_paths == ("a/note.md", "b/note.md")


def test_alias_match_when_unique() -> None:
    known = frozenset({"backend.md"})
    alias_index = {"Backend Notes": ("backend.md",)}
    outcome = resolve_link(
        _link("Backend Notes"), known_relative_paths=known, alias_index=alias_index
    )
    assert isinstance(outcome, ResolvedKnowledgeLink)
    assert outcome.target_relative_path == "backend.md"
    assert outcome.match_kind == LinkMatchKind.ALIAS


def test_ambiguous_alias_shared_by_two_notes() -> None:
    known = frozenset({"a.md", "b.md"})
    alias_index = {"Shared Alias": ("a.md", "b.md")}
    outcome = resolve_link(
        _link("Shared Alias"), known_relative_paths=known, alias_index=alias_index
    )
    assert isinstance(outcome, AmbiguousKnowledgeLink)
    assert outcome.candidate_relative_paths == ("a.md", "b.md")


def test_alias_and_filename_match_combined_when_different_notes_ambiguous() -> None:
    # "dup" matches "a/dup.md" by filename stem and "other.md" by alias --
    # neither is an *exact relative-path* match, so both remain live
    # candidates and the link is ambiguous.
    known = frozenset({"a/dup.md", "other.md"})
    alias_index = {"dup": ("other.md",)}
    outcome = resolve_link(_link("dup"), known_relative_paths=known, alias_index=alias_index)
    assert isinstance(outcome, AmbiguousKnowledgeLink)
    assert outcome.candidate_relative_paths == ("a/dup.md", "other.md")


def test_unresolved_when_nothing_matches() -> None:
    known = frozenset({"a.md"})
    outcome = resolve_link(_link("does-not-exist"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, UnresolvedKnowledgeLink)


def test_blank_target_is_unresolved() -> None:
    outcome = resolve_link(_link("   "), known_relative_paths=frozenset(), alias_index={})
    assert isinstance(outcome, UnresolvedKnowledgeLink)


def test_never_guesses_ambiguous_candidate() -> None:
    """No matter how the candidates were derived (filename or alias),
    more than one always yields `AmbiguousKnowledgeLink`, never a
    silently-picked winner."""
    known = frozenset({"x/dup.md", "y/dup.md", "z/dup.md"})
    outcome = resolve_link(_link("dup"), known_relative_paths=known, alias_index={})
    assert isinstance(outcome, AmbiguousKnowledgeLink)
    assert len(outcome.candidate_relative_paths) == 3
