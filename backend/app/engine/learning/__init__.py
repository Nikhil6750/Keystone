"""Stage 5A: Learning Core + Agent Passports.

Architecture:

    Execution -> Verification -> Learning Event -> Metric Aggregator ->
    Agent Passport -> RoutingEvidenceProvider -> existing Stage 4B Router

`events.py` defines `LearningEvent`, the raw, provider-neutral record of
one completed execution attempt -- execution outcome and verification
outcome kept as two separate fields, never collapsed into one boolean.
`aggregation.py` is the Metric Aggregator: pure, deterministic functions
reducing a list of `LearningEvent`s into `AgentPassportMetricBucket`/
`VerificationMetrics` values. `passport.py` rebuilds a `LearningPassport`
(wrapping the existing, unmodified `AgentPassport` contract) from raw
events -- raw events are always the source of truth; a passport is only
ever a recomputation, never hand-edited or independently authoritative.
`evidence.py` adapts a `LearningPassport` into the existing
`RoutingEvidenceProvider` Protocol so it plugs into `Router(evidence=...)`
without any change to routing/scoring semantics.

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
    percentile,
)
from app.engine.learning.errors import LearningEngineError, MalformedLearningEventError
from app.engine.learning.events import LearningEvent
from app.engine.learning.evidence import PassportEvidenceProvider, build_passport_evidence_provider
from app.engine.learning.passport import LearningPassport, rebuild_all_passports, rebuild_passport

__all__ = [
    "MIN_SAMPLE_SIZE_FOR_CONFIDENCE",
    "LearningBucket",
    "LearningEngineError",
    "LearningEvent",
    "LearningPassport",
    "MalformedLearningEventError",
    "PassportEvidenceProvider",
    "VerificationMetrics",
    "build_passport_evidence_provider",
    "bucket_from_events",
    "count_failure_categories",
    "group_and_bucket",
    "group_by_capability_and_bucket",
    "percentile",
    "rebuild_all_passports",
    "rebuild_passport",
]
