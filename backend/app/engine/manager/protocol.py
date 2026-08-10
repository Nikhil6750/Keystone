"""`ManagerModel`: the provider-neutral protocol Stage 8B's Nemotron adapter
(and any future provider) implements. No provider-specific import lives in
this package -- see the module docstring in `__init__.py`.

`propose()` is `async` to match `app.contracts.adapter.AgentAdapter`'s own
`describe`/`capabilities` (sync, pure metadata) vs. `verify`/`health`/
`execute`/`cancel` (async, may perform network I/O) split: a manager model
call is I/O-bound exactly like `AgentAdapter.execute()`, so it gets the same
treatment. Nothing in this module performs any I/O itself.
"""

from typing import Any, Protocol

from pydantic import ValidationError

from app.engine.manager.errors import ManagerInvalidResponseError
from app.engine.manager.models import ManagerRequest, ManagerResponse


class ManagerModel(Protocol):
    """One provider-neutral manager/reasoning model.

    Implementations MUST NOT mutate any Keystone deterministic state, call
    `WorkflowEngine`, execute shell commands, or return chain-of-thought.
    They MUST raise a typed `app.engine.manager.errors.ManagerError`
    subclass on failure rather than a bare/opaque exception, and MUST NOT
    retry internally -- `ManagerOrchestrator` calls `propose()` at most once
    per orchestration pass.
    """

    def identifier(self) -> str:
        """A short, safe identifier for this manager model (a provider or
        model name only -- never a credential, session detail, or prompt)."""
        ...

    async def propose(self, request: ManagerRequest) -> ManagerResponse:
        """Produce one structured proposal for `request`.

        Raises a typed `ManagerError` subclass on failure. Never returns
        `None` and never returns a partially-filled response silently --
        an incomplete proposal is expressed through `ManagerResponse`'s own
        optional fields (e.g. `clarification_required`), not by omitting
        validation.
        """
        ...


def parse_manager_response(raw: dict[str, Any]) -> ManagerResponse:
    """Parse an untyped payload (e.g. a future provider adapter's raw JSON)
    into a `ManagerResponse`, converting a `pydantic.ValidationError` into
    the typed `ManagerInvalidResponseError` rather than leaking a raw
    provider payload or pydantic's own error internals to the caller.

    Not used by anything in Stage 8A itself (there is no real provider
    yet) -- provided so a Stage 8B provider adapter has one canonical,
    already-tested place to convert "the provider sent us something" into
    "we have a well-formed `ManagerResponse`, or a typed rejection."
    """
    try:
        return ManagerResponse.model_validate(raw)
    except ValidationError as exc:
        raise ManagerInvalidResponseError(
            f"manager response failed to parse into a well-formed ManagerResponse: "
            f"{exc.error_count()} validation error(s)"
        ) from exc


__all__ = ["ManagerModel", "parse_manager_response"]
