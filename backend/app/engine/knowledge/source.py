"""`KnowledgeSource`: the provider-neutral seam future knowledge backends
plug into.

Mirrors `app.engine.routing.evidence.RoutingEvidenceProvider`'s established
pattern: a structural `Protocol` (duck-typed, no inheritance required), one
default in-memory implementation for this stage's own tests, and every
real backend arriving in a later stage without any change to this
interface or to the engine code that consumes it (`chunking.py`/
`index.py`/`retrieval.py`).

Future adapters (none implemented in Stage 6A):

- `ObsidianKnowledgeSource` (Stage 6B) -- reads a local vault, translates
  each note into a `KnowledgeDocument` (never exposing the vault's
  absolute filesystem path -- see `models.py`'s safety rules).
- `RepositoryKnowledgeSource` -- reads tracked source/doc files from a
  registered repository.
- `DocumentationKnowledgeSource` -- reads a documentation site/directory.
- `ExecutionHistoryKnowledgeSource` -- surfaces past execution/verification
  evidence (e.g. Stage 5's `LearningPassport`s) as searchable knowledge.

Stage 6A itself performs no filesystem access and makes no provider-specific
assumptions -- `InMemoryKnowledgeSource` is the only implementation here,
used for Stage 6A's own tests and as a template for later adapters.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.engine.knowledge.models import KnowledgeDocument


class KnowledgeSource(Protocol):
    """Provider-neutral source of `KnowledgeDocument`s."""

    @property
    def source_id(self) -> str:
        """This source's stable, opaque identifier."""
        ...

    def list_documents(self) -> list[KnowledgeDocument]:
        """Every currently-available document from this source, in a
        stable, deterministic order. Never performs I/O with
        provider-specific side effects visible to the caller -- a source
        implementation may cache internally, but two calls with no
        intervening state change must return equal document lists."""
        ...


@dataclass(frozen=True)
class InMemoryKnowledgeSource:
    """The only `KnowledgeSource` implementation Stage 6A provides: a
    fixed, in-memory collection of documents, for tests and as a reference
    implementation of the Protocol. No filesystem access."""

    source_id: str
    documents: tuple[KnowledgeDocument, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be blank")
        mismatched = [doc.document_id for doc in self.documents if doc.source_id != self.source_id]
        if mismatched:
            raise ValueError(
                f"documents {mismatched} have a source_id that does not match "
                f"this source's source_id {self.source_id!r}"
            )

    def list_documents(self) -> list[KnowledgeDocument]:
        return list(self.documents)


__all__ = ["InMemoryKnowledgeSource", "KnowledgeSource"]
