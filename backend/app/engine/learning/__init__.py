"""Stage 5A/5B: Learning Core + Agent Passports + Evidence-Based
Recommendations.

Architecture:

    Execution -> Verification -> Learning Event -> Metric Aggregator ->
    Agent Passport -> RoutingEvidenceProvider -> existing Stage 4B Router
                            |
                            v
                    LearningPolicy.recommend(...)
                            |
                            v
                    LearningRecommendation (advisory only)

`events.py` defines `LearningEvent`, the raw, provider-neutral record of
one completed execution attempt -- execution outcome and verification
outcome kept as two separate fields, never collapsed into one boolean.
`aggregation.py` is the Metric Aggregator: pure, deterministic functions
reducing a list of `LearningEvent`s into `AgentPassportMetricBucket`/
`VerificationMetrics` values (overall, task type, repository, capability,
and the joint repository+task-type dimension). `passport.py` rebuilds a
`LearningPassport` (wrapping the existing, unmodified `AgentPassport`
contract) from raw events -- raw events are always the source of truth; a
passport is only ever a recomputation, never hand-edited or independently
authoritative. `evidence.py` adapts a `LearningPassport` into the existing
`RoutingEvidenceProvider` Protocol so it plugs into `Router(evidence=...)`
without any change to routing/scoring semantics.

Stage 5B (`scoring.py`, `recommendation.py`, `policy.py`) answers "based on
historical VERIFIED evidence, what should Keystone recommend?" -- purely
advisory: `LearningPolicy.recommend(...)` never replaces, calls, or is
called by `Router`; the Router alone remains authoritative for hard
constraints, eligibility, and the final routing decision.

Does not implement persistence, Obsidian, RAG, the benchmark runner,
Nemotron, APIs, VS Code integration, provider connectors, or any Stage 6+
work -- and does not modify `app.engine.routing`, `app.engine.verification`,
or any shared contract.
"""

from app.engine.learning.aggregation import (
    MIN_SAMPLE_SIZE_FOR_CONFIDENCE,
    LearningBucket,
    VerificationMetrics,
    bucket_from_events,
    count_failure_categories,
    group_and_bucket,
    group_by_capability_and_bucket,
    group_by_repository_task_type_and_bucket,
    percentile,
)
from app.engine.learning.errors import LearningEngineError, MalformedLearningEventError
from app.engine.learning.events import LearningEvent
from app.engine.learning.evidence import PassportEvidenceProvider, build_passport_evidence_provider
from app.engine.learning.passport import LearningPassport, rebuild_all_passports, rebuild_passport
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import (
    CAPABILITY_VERIFIED_HISTORY,
    LOW_SAMPLE_SIZE,
    NO_VERIFIED_EVIDENCE,
    OVERALL_VERIFIED_HISTORY,
    REASON_CODES,
    REPOSITORY_VERIFIED_HISTORY,
    RETRY_HISTORY,
    TASK_TYPE_VERIFIED_HISTORY,
    VERIFICATION_FAILURE_HISTORY,
    AgentRecommendation,
    LearningRecommendation,
    RecommendationOutcome,
)
from app.engine.learning.scoring import (
    RecommendationWeights,
    execution_reliability,
    latency_component,
)

__all__ = [
    "CAPABILITY_VERIFIED_HISTORY",
    "LOW_SAMPLE_SIZE",
    "MIN_SAMPLE_SIZE_FOR_CONFIDENCE",
    "NO_VERIFIED_EVIDENCE",
    "OVERALL_VERIFIED_HISTORY",
    "REASON_CODES",
    "REPOSITORY_VERIFIED_HISTORY",
    "RETRY_HISTORY",
    "TASK_TYPE_VERIFIED_HISTORY",
    "VERIFICATION_FAILURE_HISTORY",
    "AgentRecommendation",
    "LearningBucket",
    "LearningEngineError",
    "LearningEvent",
    "LearningPassport",
    "LearningPolicy",
    "LearningRecommendation",
    "MalformedLearningEventError",
    "PassportEvidenceProvider",
    "RecommendationOutcome",
    "RecommendationWeights",
    "VerificationMetrics",
    "build_passport_evidence_provider",
    "bucket_from_events",
    "count_failure_categories",
    "execution_reliability",
    "group_and_bucket",
    "group_by_capability_and_bucket",
    "group_by_repository_task_type_and_bucket",
    "latency_component",
    "percentile",
    "rebuild_all_passports",
    "rebuild_passport",
]
