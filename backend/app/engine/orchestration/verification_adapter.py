"""Bridges a completed `StepAttempt`'s output into Stage 4E's
`ObservedOutcome` (`app.engine.verification.evaluators`).

Architecture discovery confirmed `ObservedOutcome` is deliberately never
built by the verification engine itself -- it is "Stage 4E's structured
stand-in for whatever the Workflow Engine already captured while actually
running the step," and no adapter from `StepAttempt`/`AgentExecutor`
output to it existed before Stage 8C.1. This module is that adapter, and
it is intentionally trivial: it never reinterprets, renames, or guesses at
executor output keys (`"output"`, `"exit_code"`, `"tests_total"`, etc. are
each evaluator's own documented `observed.data` contract,
`app.engine.verification.evaluators`) -- it passes the executor's own
result payload through unchanged. An executor whose output does not
already carry the keys a given `ExpectedOutcome.evaluator_type` needs
simply yields `VerificationStatus.INCONCLUSIVE` for that check, exactly as
the evaluator already documents; this module never fabricates a missing
key to force a PASSED/FAILED verdict.
"""

from typing import Any

from app.engine.verification.evaluators import ObservedOutcome


def build_observed_outcome(output_payload: dict[str, Any] | None) -> ObservedOutcome:
    """`output_payload` is a completed `StepAttempt.output_payload` (or an
    `AgentExecutor.execute()` result dict) -- passed through as
    `ObservedOutcome.data` unchanged. `None`/empty maps to an empty
    `ObservedOutcome`, which every evaluator already treats as "no
    evidence provided" (`INCONCLUSIVE`), never a fabricated failure."""
    return ObservedOutcome(data=dict(output_payload) if output_payload else {})


__all__ = ["build_observed_outcome"]
