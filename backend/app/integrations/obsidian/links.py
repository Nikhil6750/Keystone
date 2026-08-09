"""Deterministic link resolution against a known vault note set.

**Exact relative-path match always wins outright** (Stage 6B section 11)
-- the moment a link's target matches a real note path, resolution stops
there, before filename/alias candidates are even computed. Failing that,
filename-stem matches and frontmatter-alias matches are combined into one
candidate set: exactly one candidate => resolved, more than one =>
`AmbiguousKnowledgeLink` (never guessed), zero => `UnresolvedKnowledgeLink`.

**Plain Markdown links are note-relative; wikilinks are vault-relative.**
`[text](path)` follows ordinary CommonMark convention -- resolved
relative to the directory of the note containing it, via pure string
manipulation (`posixpath`, never a filesystem call, so a target that
normalizes outside the vault can never escape anything -- it simply never
matches a known path and resolves as unresolved). `[[wikilink]]` targets
follow Obsidian's own convention instead: matched directly against
vault-root-relative note paths/filenames, exactly as written.
"""

import posixpath

from app.integrations.markdown.models import MarkdownLinkKind, MarkdownNote
from app.integrations.obsidian.models import (
    AmbiguousKnowledgeLink,
    KnowledgeLink,
    LinkMatchKind,
    ObsidianWikiLink,
    ResolvedKnowledgeLink,
    UnresolvedKnowledgeLink,
)

ResolutionOutcome = ResolvedKnowledgeLink | UnresolvedKnowledgeLink | AmbiguousKnowledgeLink


def _strip_md_suffix(value: str) -> str:
    return value[:-3] if value.lower().endswith(".md") else value


def _note_stem(relative_path: str) -> str:
    return _strip_md_suffix(relative_path.rsplit("/", 1)[-1])


def _normalize_relative_target(source_relative_path: str, target: str) -> str:
    source_dir = posixpath.dirname(source_relative_path)
    joined = posixpath.join(source_dir, target) if source_dir else target
    return posixpath.normpath(joined).replace("\\", "/")


def normalize_generic_links(note: MarkdownNote) -> tuple[KnowledgeLink, ...]:
    """`note`'s plain `[text](target)` links, normalized to
    `KnowledgeLink`. External targets (`http://`, `file://`, `mailto:`,
    ...) are dropped here -- they remain represented on `MarkdownNote.
    links` itself, but are never resolution candidates."""
    links: list[KnowledgeLink] = []
    for link in note.links:
        if link.kind is MarkdownLinkKind.EXTERNAL:
            continue
        raw_target, _, raw_heading = link.target.partition("#")
        raw_target = raw_target.strip()
        if not raw_target:
            continue
        links.append(
            KnowledgeLink(
                source_relative_path=note.relative_path,
                target_text=_normalize_relative_target(note.relative_path, raw_target),
                is_wikilink=False,
                heading=raw_heading.strip() or None,
                alias=None,
            )
        )
    return tuple(links)


def normalize_wikilinks(
    source_relative_path: str, wikilinks: tuple[ObsidianWikiLink, ...]
) -> tuple[KnowledgeLink, ...]:
    return tuple(
        KnowledgeLink(
            source_relative_path=source_relative_path,
            target_text=wikilink.target,
            is_wikilink=True,
            heading=wikilink.heading,
            alias=wikilink.alias,
        )
        for wikilink in wikilinks
    )


def resolve_link(
    link: KnowledgeLink,
    *,
    known_relative_paths: frozenset[str],
    alias_index: dict[str, tuple[str, ...]],
) -> ResolutionOutcome:
    """Resolve one `KnowledgeLink` against `known_relative_paths` (every
    note currently in the vault) and `alias_index` (frontmatter alias ->
    the notes declaring it). Never mutates either input."""
    target = link.target_text.strip()
    if not target:
        return UnresolvedKnowledgeLink(link=link)

    exact_candidate = target if target.lower().endswith(".md") else f"{target}.md"
    if exact_candidate in known_relative_paths:
        return ResolvedKnowledgeLink(
            link=link, target_relative_path=exact_candidate, match_kind=LinkMatchKind.EXACT_PATH
        )

    stem = _strip_md_suffix(target.rsplit("/", 1)[-1])
    filename_matches = {path for path in known_relative_paths if _note_stem(path) == stem}
    alias_matches = set(alias_index.get(target, ()))
    candidates = filename_matches | alias_matches

    if len(candidates) > 1:
        return AmbiguousKnowledgeLink(link=link, candidate_relative_paths=tuple(sorted(candidates)))
    if len(candidates) == 1:
        (only,) = candidates
        match_kind = LinkMatchKind.FILENAME if only in filename_matches else LinkMatchKind.ALIAS
        return ResolvedKnowledgeLink(link=link, target_relative_path=only, match_kind=match_kind)
    return UnresolvedKnowledgeLink(link=link)


__all__ = [
    "ResolutionOutcome",
    "normalize_generic_links",
    "normalize_wikilinks",
    "resolve_link",
]
