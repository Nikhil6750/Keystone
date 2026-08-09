"""Typed exception hierarchy for the Obsidian vault adapter."""

from app.integrations.markdown.errors import MarkdownIntegrationError


class ObsidianIntegrationError(MarkdownIntegrationError):
    """Base class for typed Stage 6B Obsidian-adapter errors. Subclasses
    `MarkdownIntegrationError` since an Obsidian vault is, underneath,
    still a `MarkdownKnowledgeSource` -- every generic Markdown failure
    mode applies here too."""


class VaultConfigError(ObsidianIntegrationError):
    """Raised for an invalid `ObsidianVaultConfig`: a missing/non-directory
    root, or a blank `source_id`."""


__all__ = ["ObsidianIntegrationError", "VaultConfigError"]
