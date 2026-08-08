"""Typed exception hierarchy for the Stage 5 persistence layer."""


class PersistenceError(ValueError):
    """Base class for typed Stage 5 persistence errors."""


class LearningEventConflictError(PersistenceError):
    """Raised when a `LearningEvent` is recorded with an `event_id` that
    already exists in raw history, but the new event's immutable observed
    facts (execution/verification outcome, cost, duration, etc.) conflict
    with what was already stored.

    Raw execution history is the source of truth and is never silently
    rewritten: a byte-identical replay of the same `event_id` is a safe,
    idempotent no-op (see `ExecutionHistoryRepository.record_event`), but a
    conflicting replay -- e.g. the same `event_id` reported `PASSED` once
    and `FAILED` another time -- always raises this error instead of
    overwriting the historical record.
    """

    def __init__(self, event_id: str, conflicting_fields: tuple[str, ...]) -> None:
        self.event_id = event_id
        self.conflicting_fields = conflicting_fields
        fields = ", ".join(conflicting_fields)
        super().__init__(
            f"LearningEvent '{event_id}' already exists with different observable "
            f"facts (conflicting field(s): {fields}) -- raw history is never "
            "silently rewritten"
        )


__all__ = ["LearningEventConflictError", "PersistenceError"]
