"""`AdaptiveRetrievalPolicy`: the single, explicit configuration surface
controlling whether, and how conservatively, Stage 7.5 may adjust Stage 6A's
base retrieval ranking.

**Conservative defaults, static by default.** `enabled=False` -- an
`AdaptiveRetriever` built with the default policy always reproduces Stage
6A's base retrieval ordering exactly (see `reranking.py`). `minimum_verified_samples`
defaults to Stage 5's own `MIN_SAMPLE_SIZE_FOR_CONFIDENCE` (imported, never
redefined or duplicated) so a chunk's adaptive adjustment is never driven
by one or two noisy observations. `allow_benchmark_evidence` defaults to
`False`: benchmark-informed cold start is opt-in only, never automatic.

**No hidden global configuration.** This is a plain, caller-constructed,
frozen value object -- there is no process-wide singleton or module-level
mutable policy anywhere in Stage 7.5. Every function that needs a policy
takes one as an explicit argument.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.engine.adaptive_retrieval.errors import MalformedAdaptiveRetrievalPolicyError
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.learning.aggregation import MIN_SAMPLE_SIZE_FOR_CONFIDENCE


@dataclass(frozen=True)
class AdaptiveRetrievalPolicy:
    """Controls whether adaptive re-ranking runs at all, how much verified
    evidence it requires before trusting a chunk's history, how far it may
    move a score, and which evidence sources it may draw on."""

    enabled: bool = False
    minimum_verified_samples: int = MIN_SAMPLE_SIZE_FOR_CONFIDENCE
    max_positive_adjustment: float = 0.15
    max_negative_adjustment: float = 0.15
    allow_benchmark_evidence: bool = False
    allow_production_evidence: bool = True

    def __post_init__(self) -> None:
        if self.minimum_verified_samples < 1:
            raise MalformedAdaptiveRetrievalPolicyError(
                "minimum_verified_samples must be at least 1"
            )
        if self.max_positive_adjustment < 0.0:
            raise MalformedAdaptiveRetrievalPolicyError(
                "max_positive_adjustment must not be negative"
            )
        if self.max_negative_adjustment < 0.0:
            raise MalformedAdaptiveRetrievalPolicyError(
                "max_negative_adjustment must not be negative"
            )
        if not self.allow_benchmark_evidence and not self.allow_production_evidence:
            raise MalformedAdaptiveRetrievalPolicyError(
                "at least one of allow_benchmark_evidence/allow_production_evidence "
                "must be True, or no evidence source could ever be used"
            )

    def production_feedback(self, feedback: Iterable[RetrievalFeedback]) -> list[RetrievalFeedback]:
        """Only `EvidenceSource.PRODUCTION` feedback, or `[]` if
        `allow_production_evidence` is `False`. Deliberately returns a
        *separate* list from `benchmark_feedback` rather than one combined
        filter -- `rebuild_all_retrieval_passports` must be called once per
        source and the two resulting passport dicts passed to
        `AdaptiveRetriever.retrieve` as the distinct
        `production_passports`/`benchmark_passports` arguments. There is no
        single-call helper that returns one blended list here on purpose:
        that shape would invite exactly the "silently combine benchmark and
        production reliability into one opaque number" mistake Stage 7.5
        must avoid."""
        if not self.allow_production_evidence:
            return []
        return [item for item in feedback if item.evidence_source is EvidenceSource.PRODUCTION]

    def benchmark_feedback(self, feedback: Iterable[RetrievalFeedback]) -> list[RetrievalFeedback]:
        """Only `EvidenceSource.BENCHMARK` feedback, or `[]` if
        `allow_benchmark_evidence` is `False` (the default) -- see
        `production_feedback`'s docstring for why this is a separate method
        rather than one combined filter."""
        if not self.allow_benchmark_evidence:
            return []
        return [item for item in feedback if item.evidence_source is EvidenceSource.BENCHMARK]


__all__ = ["AdaptiveRetrievalPolicy"]
