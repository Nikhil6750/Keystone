"""`ObsidianVaultAdapter`: the first rich Markdown adapter, composing a
`MarkdownKnowledgeSource` (generic scanning/parsing/`KnowledgeDocument`
mapping, unmodified) with Obsidian-only concerns -- `.obsidian/**`
exclusion, wikilink parsing, and the vault link graph.

    Obsidian Vault -> ObsidianVaultAdapter -> MarkdownKnowledgeSource
        -> same Stage 6A Knowledge Engine

`ObsidianVaultAdapter` itself satisfies `app.engine.knowledge.source.
KnowledgeSource` (structural `Protocol`: `source_id` + `list_documents()`)
by delegating straight to its internal `MarkdownKnowledgeSource` -- no
reimplementation, no second scanner, no second `KnowledgeDocument` mapper.
"""

from app.engine.knowledge.models import KnowledgeDocument
from app.integrations.markdown.models import MarkdownNote, MarkdownScanResult
from app.integrations.markdown.source import MarkdownKnowledgeSource, MarkdownSourceConfig
from app.integrations.obsidian.graph import build_link_graph
from app.integrations.obsidian.models import ObsidianVaultConfig, VaultLinkGraph

SOURCE_KIND_OBSIDIAN = "obsidian"
OBSIDIAN_EXCLUDED_DIR_NAME = ".obsidian"


class ObsidianVaultAdapter:
    """Read-only Obsidian vault adapter. Never writes, renames, moves, or
    deletes anything beneath the vault root, and never scans
    `.obsidian/**` at all (excluded up front, the same way `.git` is)."""

    def __init__(self, config: ObsidianVaultConfig) -> None:
        self._config = config
        self._markdown_source = MarkdownKnowledgeSource(
            MarkdownSourceConfig(
                root=config.root,
                source_id=config.source_id,
                source_kind=SOURCE_KIND_OBSIDIAN,
                extra_excluded_dir_names=frozenset({OBSIDIAN_EXCLUDED_DIR_NAME})
                | config.extra_excluded_dir_names,
            )
        )

    @property
    def source_id(self) -> str:
        return self._config.source_id

    @property
    def markdown_source(self) -> MarkdownKnowledgeSource:
        """The underlying generic source -- exposed so callers that only
        need Stage 6A-compatible scanning/sync (`app.integrations.
        markdown.sync.sync_source`) can use it directly, without this
        adapter reimplementing that path."""
        return self._markdown_source

    def list_documents(self) -> list[KnowledgeDocument]:
        """`KnowledgeSource` Protocol entry point -- delegates entirely to
        the underlying `MarkdownKnowledgeSource`."""
        return self._markdown_source.list_documents()

    def scan(self) -> MarkdownScanResult:
        """Every note (and every failure) for this vault, with
        `.obsidian/**` already excluded."""
        return self._markdown_source.scan()

    def build_link_graph(self) -> VaultLinkGraph:
        """The vault's complete, deterministic link graph -- resolved,
        unresolved, and ambiguous links, plus backlinks -- built from
        every currently-parseable note. A note that failed to parse
        (`scan().failures`) contributes no links and is never a
        resolution target."""
        notes: tuple[MarkdownNote, ...] = self.scan().notes
        return build_link_graph(notes)


__all__ = ["OBSIDIAN_EXCLUDED_DIR_NAME", "SOURCE_KIND_OBSIDIAN", "ObsidianVaultAdapter"]
