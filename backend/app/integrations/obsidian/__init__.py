"""Stage 6B: Obsidian Vault Adapter -- the first rich Markdown adapter.

    Obsidian Vault -> ObsidianVaultAdapter -> MarkdownKnowledgeSource
        -> same Stage 6A Knowledge Engine

Everything Obsidian-specific (`.obsidian/**` exclusion, `[[wikilink]]`
syntax, link resolution, the backlink graph) lives in this package only.
Generic scanning, frontmatter parsing, plain-link representation, safe
`KnowledgeDocument` mapping, and incremental sync all come from `app.
integrations.markdown`, unmodified and un-duplicated.
"""

from app.integrations.obsidian.adapter import (
    OBSIDIAN_EXCLUDED_DIR_NAME,
    SOURCE_KIND_OBSIDIAN,
    ObsidianVaultAdapter,
)
from app.integrations.obsidian.errors import ObsidianIntegrationError, VaultConfigError
from app.integrations.obsidian.graph import build_link_graph
from app.integrations.obsidian.links import (
    ResolutionOutcome,
    normalize_generic_links,
    normalize_wikilinks,
    resolve_link,
)
from app.integrations.obsidian.models import (
    AmbiguousKnowledgeLink,
    KnowledgeBacklink,
    KnowledgeLink,
    LinkMatchKind,
    ObsidianVaultConfig,
    ObsidianWikiLink,
    ResolvedKnowledgeLink,
    UnresolvedKnowledgeLink,
    VaultLinkGraph,
)
from app.integrations.obsidian.parser import parse_wikilinks

__all__ = [
    "OBSIDIAN_EXCLUDED_DIR_NAME",
    "SOURCE_KIND_OBSIDIAN",
    "AmbiguousKnowledgeLink",
    "KnowledgeBacklink",
    "KnowledgeLink",
    "LinkMatchKind",
    "ObsidianIntegrationError",
    "ObsidianVaultAdapter",
    "ObsidianVaultConfig",
    "ObsidianWikiLink",
    "ResolutionOutcome",
    "ResolvedKnowledgeLink",
    "UnresolvedKnowledgeLink",
    "VaultConfigError",
    "VaultLinkGraph",
    "build_link_graph",
    "normalize_generic_links",
    "normalize_wikilinks",
    "parse_wikilinks",
    "resolve_link",
]
