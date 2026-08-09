"""`sync_source`: deterministic, incremental synchronization of one
`MarkdownKnowledgeSource` into a Stage 6A `KnowledgeIndex`.

**Change detection is content-hash based, never mtime-based.** A note is
`unchanged` iff its current whole-file `content_hash` equals the hash
recorded in `KnowledgeSourceStateRepository` from the previous sync;
`mtime` is never consulted for this decision (Stage 6B, section 16 -- "
mtime may be used as an optimization only," which this implementation does
not even need, since re-parsing every note on each call is already cheap
and keeps the diff exact).

**Reuses Stage 6A's chunker unconditionally.** `chunk_document` (`app.
engine.knowledge.chunking`) is the only chunking call in this module --
`added`/`updated` notes are chunked and written via `KnowledgeIndex.
upsert_document`, which itself guarantees no stale chunk survives an
update. Nothing here reimplements chunking or indexing.

**A rename is "old removed, new added."** Because identity is
`(source_id, relative_path)` (see `app.integrations.markdown.source.
build_document_id`), a note that moves to a new relative path has no
stable identity linking it to its old path -- the old path disappears
from the current scan (-> `deleted`) and the new path appears fresh (->
`added`), exactly as Stage 6B section 14 specifies.

**A parse failure never deletes previously-good state.** If a
`relative_path` that succeeded in a prior sync now fails to parse (e.g.
its content was emptied), it is reported in `SyncResult.failed` and its
existing index entry / sync-state entry is left exactly as it was --
never removed just because the *current* read failed. A `relative_path`
that disappears from disk entirely (not merely unparseable) is the only
case that becomes `deleted`.

**No database.** State persistence goes through the storage-neutral
`KnowledgeSourceStateRepository` Protocol (`app.integrations.markdown.
state`) -- Stage 6B intentionally ships only `InMemoryKnowledgeSource
StateRepository`; a later stage can add real persistence behind that same
interface without touching this function.
"""

from app.engine.knowledge.chunking import ChunkingPolicy, chunk_document
from app.engine.knowledge.index import KnowledgeIndex
from app.integrations.markdown.models import MarkdownNote, SyncEntry, SyncResult
from app.integrations.markdown.source import MarkdownKnowledgeSource, note_to_document
from app.integrations.markdown.state import DocumentSyncState, KnowledgeSourceStateRepository


def sync_source(
    source: MarkdownKnowledgeSource,
    index: KnowledgeIndex,
    state_repository: KnowledgeSourceStateRepository,
    *,
    chunking_policy: ChunkingPolicy | None = None,
) -> SyncResult:
    """Scan `source`, diff against `state_repository`'s last-known state
    for `source.source_id`, apply the diff to `index`, persist the new
    state, and return exactly what changed. Idempotent: calling this
    again immediately afterward, with nothing changed on disk, yields an
    all-`unchanged` `SyncResult` and mutates neither `index` nor the
    stored state."""
    scan_result = source.scan()
    previous_state = state_repository.get_state(source.source_id)

    notes_by_path: dict[str, MarkdownNote] = {
        note.relative_path: note for note in scan_result.notes
    }
    failed_paths = {failure.relative_path for failure in scan_result.failures}

    added: list[SyncEntry] = []
    updated: list[SyncEntry] = []
    unchanged: list[SyncEntry] = []
    deleted: list[SyncEntry] = []
    new_state = dict(previous_state)

    current_paths = set(notes_by_path)
    previous_paths = set(previous_state)

    for relative_path in sorted(current_paths):
        note = notes_by_path[relative_path]
        previous = previous_state.get(relative_path)

        if previous is not None and previous.content_hash == note.content_hash:
            unchanged.append(
                SyncEntry(relative_path=relative_path, document_id=previous.document_id)
            )
            continue

        document = note_to_document(source.source_id, source.source_kind, note)
        chunks = chunk_document(document, policy=chunking_policy)
        index.upsert_document(document, chunks)
        entry = SyncEntry(relative_path=relative_path, document_id=document.document_id)
        (added if previous is None else updated).append(entry)
        new_state[relative_path] = DocumentSyncState(
            relative_path=relative_path,
            document_id=document.document_id,
            content_hash=note.content_hash,
        )

    for relative_path in sorted(previous_paths - current_paths - failed_paths):
        previous = previous_state[relative_path]
        index.remove_document(previous.document_id)
        deleted.append(SyncEntry(relative_path=relative_path, document_id=previous.document_id))
        del new_state[relative_path]

    state_repository.save_state(source.source_id, new_state)

    return SyncResult(
        added=tuple(added),
        updated=tuple(updated),
        deleted=tuple(deleted),
        unchanged=tuple(unchanged),
        failed=tuple(sorted(scan_result.failures, key=lambda failure: failure.relative_path)),
    )


__all__ = ["sync_source"]
