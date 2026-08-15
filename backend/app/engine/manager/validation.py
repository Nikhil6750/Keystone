"""`ManagerProposalValidator`: the deterministic gate every `ManagerResponse`
must pass through before any part of it may influence orchestration.

Two validation layers exist in this package, deliberately separate:

1. **Structural** (`models.py`, Pydantic): shape, non-blank fields, known
   enum values (`AgentCapability`, `BenchmarkEvaluatorType`, `RecoveryAction`
   are all closed `StrEnum`s -- an unrecognized value simply cannot
   construct a `ManagerResponse`), unique task keys, known dependency
   references, no cycles, every collection/length bound. A malformed or
   oversized response cannot exist as a Python object at all.
2. **Contextual** (this module): everything that needs *both* the response
   and the request it answers -- request/response correlation, whether a
   proposed preferred agent type or capability is actually among what this
   specific request declared available, whether a recovery recommendation
   was made in a context that actually had a prior failed attempt.

`validate()` never raises -- it always returns a `ManagerValidationResult`,
so a caller (`ManagerOrchestrator`) can inspect *why* a proposal was
rejected without exception-handling control flow. `validate_or_raise()` is
the convenience wrapper for a caller that wants a hard failure instead.

**Fail closed, always.** Any unknown/unsafe reference found here rejects the
*entire* response (`accepted=False`) -- this module never drops the
offending part and silently proceeds with the rest, and never invents a
replacement value. See Stage 8A rule 7.
"""

from dataclasses import dataclass

from app.engine.manager.errors import ManagerProposalRejectedError
from app.engine.manager.models import ManagerRequest, ManagerResponse


@dataclass(frozen=True)
class ManagerValidationIssue:
    """One reason a `ManagerResponse` failed validation: a stable,
    machine-readable `code` paired with a human-readable `message` --
    mirrors `app.engine.routing.scorer.EligibilityViolation`'s shape."""

    code: str
    message: str


@dataclass(frozen=True)
class ManagerValidationResult:
    """The deterministic outcome of one `ManagerProposalValidator.validate()`
    call. `accepted=True` iff `issues` is empty -- there is no partial
    acceptance."""

    accepted: bool
    issues: tuple[ManagerValidationIssue, ...] = ()


REQUEST_ID_MISMATCH = "request_id_mismatch"
UNKNOWN_PREFERRED_AGENT_TYPE = "unknown_preferred_agent_type"
UNKNOWN_REQUIRED_CAPABILITY = "unknown_required_capability"
RECOVERY_RECOMMENDATION_WITHOUT_CONTEXT = "recovery_recommendation_without_context"


class ManagerProposalValidator:
    """Stateless: `validate` is a pure function of its two arguments."""

    def validate(
        self, response: ManagerResponse, request: ManagerRequest
    ) -> ManagerValidationResult:
        issues: list[ManagerValidationIssue] = []

        if response.request_id != request.request_id:
            issues.append(
                ManagerValidationIssue(
                    REQUEST_ID_MISMATCH,
                    f"response.request_id={response.request_id!r} does not match "
                    f"request.request_id={request.request_id!r}",
                )
            )

        known_agent_types = set(request.available_agent_types)
        known_capabilities = set(request.available_capabilities)

        for task in response.task_proposals:
            for agent_type in task.preferred_agent_types:
                if agent_type not in known_agent_types:
                    issues.append(
                        ManagerValidationIssue(
                            UNKNOWN_PREFERRED_AGENT_TYPE,
                            f"task '{task.key}' prefers unknown agent type "
                            f"{agent_type!r}; not among request.available_agent_types",
                        )
                    )
            if known_capabilities:
                for capability in task.required_capabilities:
                    if capability not in known_capabilities:
                        issues.append(
                            ManagerValidationIssue(
                                UNKNOWN_REQUIRED_CAPABILITY,
                                f"task '{task.key}' requires capability "
                                f"{capability.value!r}; not among "
                                "request.available_capabilities",
                            )
                        )

        if response.recovery_recommendation is not None and request.recovery_context is None:
            issues.append(
                ManagerValidationIssue(
                    RECOVERY_RECOMMENDATION_WITHOUT_CONTEXT,
                    "recovery_recommendation was proposed but request.recovery_context "
                    "is None -- a recovery proposal requires a prior failed attempt",
                )
            )

        return ManagerValidationResult(accepted=not issues, issues=tuple(issues))

    def validate_or_raise(
        self, response: ManagerResponse, request: ManagerRequest
    ) -> ManagerResponse:
        """Convenience wrapper: returns `response` unchanged if accepted,
        otherwise raises `ManagerProposalRejectedError` carrying every
        issue's `code`."""
        result = self.validate(response, request)
        if not result.accepted:
            codes = tuple(issue.code for issue in result.issues)
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in result.issues)
            raise ManagerProposalRejectedError(
                f"manager proposal failed deterministic validation: {summary}", issues=codes
            )
        return response


__all__ = [
    "RECOVERY_RECOMMENDATION_WITHOUT_CONTEXT",
    "REQUEST_ID_MISMATCH",
    "UNKNOWN_PREFERRED_AGENT_TYPE",
    "UNKNOWN_REQUIRED_CAPABILITY",
    "ManagerProposalValidator",
    "ManagerValidationIssue",
    "ManagerValidationResult",
]
