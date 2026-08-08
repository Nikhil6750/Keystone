"""Stage 4E: Verification + Recovery/Rerouting Policy + Consensus.

Architecture:

    Planner          = WHAT work exists      (app.engine.planning)
    Router           = WHO should perform it (app.engine.routing)
    Workflow Engine  = EXECUTE               (app.engine.workflow)
    Verifier         = DID IT WORK           (this package: verifier.py)
    Recovery Policy  = WHAT SHOULD HAPPEN NEXT (this package: recovery.py)

This package never executes an agent and never calls an external model.
`verify_one`/`verify_many` check already-collected, structured
`ObservedOutcome` evidence against `ExpectedOutcome` criteria using only
objective evaluators (`evaluators.py`, one per `BenchmarkEvaluatorType`
member that currently exists). `decide_recovery` turns a verification
verdict into one of `ACCEPT`/`RETRY_SAME`/`REROUTE`/`REQUEST_CONSENSUS`/
`HUMAN_REVIEW`/`FAIL`; `reroute` asks the existing, unmodified Stage 4B
`Router` for the next `RoutingDecision` without ever bypassing a hard
constraint or executing the selected candidate. `evaluate_consensus`
combines independently verified candidate outputs using only observable
evidence, never hidden reasoning.

Does not build Stage 5 Learning, Obsidian, or Nemotron integration; does not
modify provider connectors or Stage 4B routing scoring semantics; does not
expose model chain-of-thought; does not implement any API endpoint.
"""

from app.engine.verification.aggregation import AggregatedVerification, CheckOutcome, aggregate
from app.engine.verification.consensus import (
    ConsensusCandidate,
    ConsensusOutcome,
    ConsensusResult,
    evaluate_consensus,
)
from app.engine.verification.errors import (
    CommandExecutionNotConfiguredError,
    MalformedExpectedOutcomeError,
    UnsafeEvidenceError,
    UnsupportedEvaluatorError,
    VerificationEngineError,
)
from app.engine.verification.evaluators import (
    CommandExecutionOutcome,
    CommandExecutor,
    CommandSpec,
    EvaluatorOutcome,
    NullCommandExecutor,
    ObservedOutcome,
)
from app.engine.verification.recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    build_reroute_request,
    decide_recovery,
    reroute,
)
from app.engine.verification.registry import get_evaluator
from app.engine.verification.verifier import VerificationCheck, verify_many, verify_one

__all__ = [
    "AggregatedVerification",
    "CheckOutcome",
    "CommandExecutionNotConfiguredError",
    "CommandExecutionOutcome",
    "CommandExecutor",
    "CommandSpec",
    "ConsensusCandidate",
    "ConsensusOutcome",
    "ConsensusResult",
    "EvaluatorOutcome",
    "MalformedExpectedOutcomeError",
    "NullCommandExecutor",
    "ObservedOutcome",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryPolicy",
    "UnsafeEvidenceError",
    "UnsupportedEvaluatorError",
    "VerificationCheck",
    "VerificationEngineError",
    "aggregate",
    "build_reroute_request",
    "decide_recovery",
    "evaluate_consensus",
    "get_evaluator",
    "reroute",
    "verify_many",
    "verify_one",
]
