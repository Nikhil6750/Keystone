"""Typed exception hierarchy for the Stage 8A provider-neutral manager core.

Mirrors the existing per-module discipline (`app.adapters.exceptions`,
`app.engine.verification.errors`, `app.engine.learning.errors`): every
manager-related failure is a typed subclass, never a bare/opaque exception,
and never carries a provider secret or raw sensitive payload in its message.

Two distinct failure shapes, deliberately kept separate:

- `ManagerUnavailableError`/`ManagerTimeoutError`/`ManagerInvalidResponseError`
  describe the *manager model itself* failing (unreachable, too slow, or
  returned something that could not be parsed into a `ManagerResponse`) --
  analogous to `AgentAdapterError`'s failure family. A `ManagerModel`
  implementation raises these; nothing here inherits from `ValueError`,
  since these are runtime/provider failures, not caller-input-shape bugs.
- `ManagerProposalRejectedError` describes a *structurally valid*
  `ManagerResponse` that `ManagerProposalValidator` deterministically
  rejected (see `validation.py`) -- the manager model itself worked, but
  its proposal failed Keystone's own gate before it could influence
  orchestration.

`ManagerOrchestrator` (`orchestrator.py`) catches every `ManagerError`
subclass exactly once per call -- there is no retry loop anywhere in this
package -- and falls back to the existing deterministic Planner path.
"""


class ManagerError(Exception):
    """Base class for typed Stage 8A manager-core errors."""


class ManagerUnavailableError(ManagerError):
    """The configured `ManagerModel` could not be reached, is not
    configured, or otherwise cannot serve this request right now. Never
    retried automatically by this package -- the caller (`ManagerOrchestrator`)
    falls back to the deterministic Planner path instead."""

    def __init__(self, message: str = "manager model is unavailable") -> None:
        super().__init__(message)


class ManagerTimeoutError(ManagerError):
    """The `ManagerModel` call exceeded its bounded time budget.

    Raised either by a `ManagerModel` implementation itself (e.g. a future
    provider adapter converting its own HTTP client timeout) or by
    `ManagerOrchestrator`'s own `asyncio.wait_for` bound. Never retried."""

    def __init__(self, message: str = "manager model call exceeded its time budget") -> None:
        super().__init__(message)


class ManagerInvalidResponseError(ManagerError):
    """The `ManagerModel` returned something that could not be parsed into a
    well-formed `ManagerResponse` -- malformed shape, unknown enum value, or
    a bound violation. Never leaks the raw offending payload in the message;
    callers constructing this from a caught `pydantic.ValidationError` must
    summarize, not forward the raw provider payload verbatim, since it may
    contain untrusted provider output."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ManagerProposalRejectedError(ManagerError):
    """A structurally valid `ManagerResponse` failed deterministic
    `ManagerProposalValidator` validation and was rejected outright -- fail
    closed, never silently repaired or partially applied.

    `issues` carries the stable, machine-readable `ManagerValidationIssue.code`
    values that caused the rejection (see `validation.py`), for callers that
    want to branch on the specific reason without re-parsing the message.
    """

    def __init__(self, message: str, *, issues: tuple[str, ...] = ()) -> None:
        self.issues = issues
        super().__init__(message)


__all__ = [
    "ManagerError",
    "ManagerInvalidResponseError",
    "ManagerProposalRejectedError",
    "ManagerTimeoutError",
    "ManagerUnavailableError",
]
