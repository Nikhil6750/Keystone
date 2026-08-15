"""Immutable value types for Obsidian-specific syntax and the vault link
graph.

`ObsidianWikiLink` is the only type here that knows about `[[...]]`
syntax -- kept out of `app.integrations.markdown` entirely, per Stage 6B's
"generic Markdown logic MUST stay outside the Obsidian package" rule
(applied in the other direction: Obsidian-only syntax must stay *inside*
this package). Everything downstream of parsing (`KnowledgeLink` and its
resolution variants) is typed and immutable -- no `dict[str, Any]`
payload anywhere in the graph.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.integrations.obsidian.errors import VaultConfigError


@dataclass(frozen=True)
class ObsidianWikiLink:
    """One `[[target]]` / `[[target#heading]]` / `[[target|alias]]` /
    `[[target#heading|alias]]` reference, exactly as written -- never
    resolved here. `target` is the raw note reference (e.g. `"Note"` or
    `"folder/Note"`), with no `.md` extension assumed one way or the
    other; resolution (`app.integrations.obsidian.links`) normalizes
    that."""

    target: str
    heading: str | None = None
    alias: str | None = None


class LinkMatchKind(StrEnum):
    """How a link was resolved to a target note -- an explicit,
    documented ranking, never a guess. `EXACT_PATH` always wins outright
    when it applies; `FILENAME` and `ALIAS` are combined into a single
    ambiguity check (Stage 6B, section 11: "exact relative-path matches
    should win," multiple other candidates => ambiguous, never
    silently chosen)."""

    EXACT_PATH = "exact_path"
    FILENAME = "filename"
    ALIAS = "alias"


@dataclass(frozen=True)
class KnowledgeLink:
    """One link found in one note, normalized to a common shape shared by
    plain Markdown links and Obsidian wikilinks alike, before
    resolution."""

    source_relative_path: str
    target_text: str
    is_wikilink: bool
    heading: str | None = None
    alias: str | None = None


@dataclass(frozen=True)
class ResolvedKnowledgeLink:
    """One `KnowledgeLink` resolved to exactly one target note."""

    link: KnowledgeLink
    target_relative_path: str
    match_kind: LinkMatchKind


@dataclass(frozen=True)
class UnresolvedKnowledgeLink:
    """One `KnowledgeLink` that matched no known note in the vault."""

    link: KnowledgeLink


@dataclass(frozen=True)
class AmbiguousKnowledgeLink:
    """One `KnowledgeLink` that matched more than one candidate note.
    Never silently resolved to one of them -- `candidate_relative_paths`
    is the full, sorted set of possibilities, left for a caller (or a
    human) to disambiguate."""

    link: KnowledgeLink
    candidate_relative_paths: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeBacklink:
    """Every note that links to `target_relative_path`, sorted
    deterministically -- the inverse of `ResolvedKnowledgeLink`. Never
    written back into any note; purely a derived, in-memory view."""

    target_relative_path: str
    source_relative_paths: tuple[str, ...]


@dataclass(frozen=True)
class VaultLinkGraph:
    """The complete, deterministic link graph for one vault snapshot:
    every resolved, unresolved, and ambiguous link, plus the backlink
    index derived from the resolved set. All four tuples are sorted for
    reproducibility regardless of scan order."""

    resolved: tuple[ResolvedKnowledgeLink, ...] = field(default_factory=tuple)
    unresolved: tuple[UnresolvedKnowledgeLink, ...] = field(default_factory=tuple)
    ambiguous: tuple[AmbiguousKnowledgeLink, ...] = field(default_factory=tuple)
    backlinks: tuple[KnowledgeBacklink, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ObsidianVaultConfig:
    """Explicit configuration for one `ObsidianVaultAdapter`. `root` is
    the vault root (the directory that may contain `.obsidian/`, not that
    hidden directory itself) -- canonicalized once, at adapter
    construction, exactly like `MarkdownSourceConfig.root`."""

    root: str | Path
    source_id: str
    extra_excluded_dir_names: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise VaultConfigError("source_id must not be blank")


__all__ = [
    "AmbiguousKnowledgeLink",
    "KnowledgeBacklink",
    "KnowledgeLink",
    "LinkMatchKind",
    "ObsidianVaultConfig",
    "ObsidianWikiLink",
    "ResolvedKnowledgeLink",
    "UnresolvedKnowledgeLink",
    "VaultLinkGraph",
]
