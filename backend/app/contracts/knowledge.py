"""Obsidian knowledge-backend contracts.

Data shapes only — Stage 6 implements vault indexing and retrieval.
`document_id` is an opaque identifier; `relative_path` is relative to the
registered vault root, never an absolute filesystem path, per the knowledge
backend's local-only privacy requirements.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocument(BaseModel):
    """One indexed Markdown document within a registered vault."""

    model_config = ConfigDict(from_attributes=True)

    document_id: str
    vault_id: str
    title: str
    relative_path: str
    tags: list[str] = Field(default_factory=list)
    frontmatter: dict[str, str] = Field(default_factory=dict)
    headings: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    backlinks: list[str] = Field(default_factory=list)
    content_hash: str
    size_bytes: int
    modified_at: datetime


class KnowledgeSearchResult(BaseModel):
    """One search hit against a vault's index."""

    model_config = ConfigDict(from_attributes=True)

    document_id: str
    vault_id: str
    title: str
    snippet: str
    score: float
    tags: list[str] = Field(default_factory=list)


__all__ = ["KnowledgeDocument", "KnowledgeSearchResult"]
