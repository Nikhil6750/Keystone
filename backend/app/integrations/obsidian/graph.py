"""Orchestrates link resolution across an entire vault snapshot into one
deterministic `VaultLinkGraph` -- resolved/unresolved/ambiguous links plus
the derived backlink index. A plain `MarkdownKnowledgeSource` (no
Obsidian) never builds one of these; this is the Obsidian-specific
"graph view" layer built on top of the generic Markdown parsing pipeline.

**Never written back into any note.** Every field here is a pure,
in-memory derivation from already-parsed `MarkdownNote`s -- `build_link_
graph` performs no filesystem I/O at all.

**Deterministic regardless of input order.** Notes are sorted by
`relative_path` before processing, and every output tuple is sorted by an
explicit key -- two calls with the same note *set* (in any order) always
produce byte-for-byte the same `VaultLinkGraph`.
"""

from collections import defaultdict

from app.integrations.markdown.models import MarkdownNote
from app.integrations.obsidian.links import (
    normalize_generic_links,
    normalize_wikilinks,
    resolve_link,
)
from app.integrations.obsidian.models import (
    AmbiguousKnowledgeLink,
    KnowledgeBacklink,
    ResolvedKnowledgeLink,
    UnresolvedKnowledgeLink,
    VaultLinkGraph,
)
from app.integrations.obsidian.parser import parse_wikilinks


def _build_alias_index(notes: tuple[MarkdownNote, ...]) -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = defaultdict(list)
    for note in notes:
        for alias in note.frontmatter.aliases:
            index[alias].append(note.relative_path)
    return {alias: tuple(sorted(paths)) for alias, paths in index.items()}


def build_link_graph(notes: tuple[MarkdownNote, ...]) -> VaultLinkGraph:
    """Build the complete link graph for `notes` (every note currently
    parsed from the vault)."""
    sorted_notes = tuple(sorted(notes, key=lambda note: note.relative_path))
    known_relative_paths = frozenset(note.relative_path for note in sorted_notes)
    alias_index = _build_alias_index(sorted_notes)

    resolved: list[ResolvedKnowledgeLink] = []
    unresolved: list[UnresolvedKnowledgeLink] = []
    ambiguous: list[AmbiguousKnowledgeLink] = []

    for note in sorted_notes:
        wikilinks = parse_wikilinks(note.content)
        links = normalize_generic_links(note) + normalize_wikilinks(note.relative_path, wikilinks)
        for link in links:
            outcome = resolve_link(
                link, known_relative_paths=known_relative_paths, alias_index=alias_index
            )
            if isinstance(outcome, ResolvedKnowledgeLink):
                resolved.append(outcome)
            elif isinstance(outcome, AmbiguousKnowledgeLink):
                ambiguous.append(outcome)
            else:
                unresolved.append(outcome)

    resolved_sorted = tuple(
        sorted(
            resolved,
            key=lambda r: (
                r.link.source_relative_path,
                r.target_relative_path,
                r.link.target_text,
                r.link.heading or "",
                r.link.alias or "",
            ),
        )
    )
    unresolved_sorted = tuple(
        sorted(
            unresolved,
            key=lambda u: (u.link.source_relative_path, u.link.target_text, u.link.heading or ""),
        )
    )
    ambiguous_sorted = tuple(
        sorted(ambiguous, key=lambda a: (a.link.source_relative_path, a.link.target_text))
    )

    backlink_map: dict[str, set[str]] = defaultdict(set)
    for resolved_link in resolved_sorted:
        backlink_map[resolved_link.target_relative_path].add(resolved_link.link.source_relative_path)

    backlinks = tuple(
        KnowledgeBacklink(target_relative_path=target, source_relative_paths=tuple(sorted(sources)))
        for target, sources in sorted(backlink_map.items())
    )

    return VaultLinkGraph(
        resolved=resolved_sorted,
        unresolved=unresolved_sorted,
        ambiguous=ambiguous_sorted,
        backlinks=backlinks,
    )


__all__ = ["build_link_graph"]
