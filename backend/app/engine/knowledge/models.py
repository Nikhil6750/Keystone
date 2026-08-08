"""Provider-neutral Knowledge Engine value types: `KnowledgeDocument`,
`KnowledgeChunk`, and `KnowledgeProvenance`.

**Distinct from `app.contracts.knowledge`.** That module's `KnowledgeDocument`/
`KnowledgeSearchResult` are Obsidian-vault-shaped contracts (`vault_id`,
`relative_path`, `frontmatter`, `headings`, `links`, `backlinks`) built
ahead of time for a future Obsidian-specific backend -- not a fit for
Stage 6A's explicit "must not depend on Obsidian" requirement. This module
defines separate, engine-layer, frozen-dataclass types with the same
"knowledge document/chunk" *concept* but a genuinely provider-neutral
shape; it does not import from, extend, or modify that contract module at
all. A future Obsidian adapter (Stage 6B) would translate its own vault
documents into *these* types before handing them to the engine, the same
way `PassportEvidenceProvider` (Stage 5A) adapts `LearningPassport` into
`RoutingEvidenceProvider` evidence without touching the Router's contracts.

**Deterministic identity.** `content_hash` is always computed from
`content` in `__post_init__` (SHA-256, hex) -- never caller-supplied and
trusted blindly -- so two documents/chunks with identical content always
have an identical, verifiable hash, and a caller can never construct one
with a hash that lies about its own content.

**Safe metadata, by construction.** `metadata` is restricted to
`dict[str, str]` (no open `Any`-typed value anywhere), and every key/value
pair is validated at construction: keys are checked against the shared
`reject_reasoning_shaped_keys` vocabulary (chain-of-thought, hidden
reasoning, raw prompts, ...) plus an explicit credential-shaped-key
denylist (password, secret, credential, api key, access/session token);
values are checked against an absolute-filesystem-path/traversal shape.
Nothing here can carry hidden reasoning, credentials, or a private machine
path -- not because of a policy, but because construction raises
`UnsafeKnowledgeDataError` if it would.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from app.contracts.evidence_safety import reject_reasoning_shaped_keys
from app.engine.knowledge.errors import MalformedKnowledgeDataError, UnsafeKnowledgeDataError

_ABSOLUTE_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")

_FORBIDDEN_METADATA_KEY_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "session_token",
)


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def looks_like_unsafe_local_path(value: str) -> bool:
    """True if `value` looks like an absolute filesystem path (Unix
    leading `/`, Windows drive prefix `C:\\`/`C:/`, UNC `\\\\server\\...`)
    or contains a `..` traversal segment, rather than an opaque, portable
    identifier or ordinary knowledge content."""
    if value.startswith("/") or value.startswith("\\"):
        return True
    if _ABSOLUTE_DRIVE_PATH_RE.match(value):
        return True
    segments = re.split(r"[\\/]", value)
    return ".." in segments


def validate_safe_metadata(metadata: dict[str, str]) -> None:
    """Raises `UnsafeKnowledgeDataError` if `metadata` contains a
    reasoning-shaped key, a credential-shaped key, a non-string key/value,
    or a value that looks like an absolute local filesystem path."""
    try:
        reject_reasoning_shaped_keys(metadata)
    except ValueError as exc:
        raise UnsafeKnowledgeDataError(str(exc)) from exc

    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise UnsafeKnowledgeDataError("metadata keys and values must be strings")
        normalized = _normalize_key(key)
        if any(bad in normalized for bad in _FORBIDDEN_METADATA_KEY_SUBSTRINGS):
            raise UnsafeKnowledgeDataError(
                f"metadata key {key!r} looks like a credential/secret field and is not allowed"
            )
        if looks_like_unsafe_local_path(value):
            raise UnsafeKnowledgeDataError(
                f"metadata value for {key!r} must not look like an absolute filesystem path"
            )


def _validate_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise MalformedKnowledgeDataError(f"{field_name} must not be blank")
    if looks_like_unsafe_local_path(value):
        raise UnsafeKnowledgeDataError(
            f"{field_name} must not look like an absolute filesystem path"
        )


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeProvenance:
    """Where one piece of retrieved knowledge came from -- always
    reconstructable, so a future explainability layer can answer "which
    knowledge supported this action?" without any hidden reasoning."""

    source_id: str
    document_id: str
    chunk_id: str
    heading_path: tuple[str, ...] = ()
    rank: int | None = None
    score: float | None = None


@dataclass(frozen=True)
class KnowledgeDocument:
    """One observable document from a `KnowledgeSource`, before chunking."""

    document_id: str
    source_id: str
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    modified_at: datetime | None = None
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.document_id, "document_id")
        _validate_identifier(self.source_id, "source_id")
        if not self.title.strip():
            raise MalformedKnowledgeDataError("title must not be blank")
        if not self.content.strip():
            raise MalformedKnowledgeDataError("content must not be blank")
        validate_safe_metadata(self.metadata)
        object.__setattr__(self, "content_hash", _content_hash(self.content))


@dataclass(frozen=True)
class KnowledgeChunk:
    """One deterministically-derived slice of a `KnowledgeDocument`'s content."""

    chunk_id: str
    document_id: str
    source_id: str
    content: str
    ordinal: int
    heading_path: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.chunk_id, "chunk_id")
        _validate_identifier(self.document_id, "document_id")
        _validate_identifier(self.source_id, "source_id")
        if not self.content.strip():
            raise MalformedKnowledgeDataError("content must not be blank")
        if self.ordinal < 0:
            raise MalformedKnowledgeDataError("ordinal must not be negative")
        validate_safe_metadata(self.metadata)
        object.__setattr__(self, "content_hash", _content_hash(self.content))


__all__ = [
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeProvenance",
    "looks_like_unsafe_local_path",
    "validate_safe_metadata",
]
