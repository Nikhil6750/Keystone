"""Storage-neutral sync-state seam: `KnowledgeSourceStateRepository`.

Mirrors `app.engine.knowledge.source.KnowledgeSource`'s own pattern: a
structural `Protocol` plus one in-memory reference implementation for
tests, so a later stage can add real (e.g. relational) persistence behind
this exact interface without changing `app.integrations.markdown.sync` at
all. Stage 6B deliberately adds no database-backed implementation --
see `app.integrations.markdown.sync`'s module docstring.

Markdown files on disk remain the single source of truth (Stage 6B,
section 18): everything stored here is a derived cache of "what did we
last see," used only to compute the next `added`/`updated`/`deleted`/
`unchanged` diff. Losing this state entirely and re-syncing from an empty
state degrades gracefully to "everything looks added" -- never a crash,
never a permanently wrong index (a follow-up sync against the same
Markdown tree reproduces the same semantic content either way).
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DocumentSyncState:
    """What `sync_source` last recorded for one note: its `document_id`
    and the whole-file `content_hash` it had at that point. Never a
    timestamp -- `mtime` is not semantic identity (Stage 6B, section 7)
    and plays no role in change detection here."""

    relative_path: str
    document_id: str
    content_hash: str


class KnowledgeSourceStateRepository(Protocol):
    """Storage-neutral seam for persisting one source's last-known sync
    state, keyed by `relative_path`."""

    def get_state(self, source_id: str) -> dict[str, DocumentSyncState]:
        """Every `DocumentSyncState` last saved for `source_id`, keyed by
        `relative_path`. `{}` for a source never synced before -- never
        raises for that case."""
        ...

    def save_state(self, source_id: str, state: dict[str, DocumentSyncState]) -> None:
        """Replace the entire stored state for `source_id` with `state`."""
        ...


class InMemoryKnowledgeSourceStateRepository:
    """The only `KnowledgeSourceStateRepository` implementation Stage 6B
    provides -- a fixed, in-memory mapping, for tests and as a reference
    implementation of the Protocol. Not persisted across process
    restarts; deliberately no database of any kind."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, DocumentSyncState]] = {}

    def get_state(self, source_id: str) -> dict[str, DocumentSyncState]:
        return dict(self._state.get(source_id, {}))

    def save_state(self, source_id: str, state: dict[str, DocumentSyncState]) -> None:
        self._state[source_id] = dict(state)


__all__ = [
    "DocumentSyncState",
    "InMemoryKnowledgeSourceStateRepository",
    "KnowledgeSourceStateRepository",
]
