"""Stage 7.5: Self-Learning RAG Core -- provider-neutral adaptive retrieval.

Architecture:

    Knowledge Sources
          |
    Stage 6A KnowledgeIndex
          |
    Base Retrieval (app.engine.knowledge.retrieval.search, unmodified)
          |
    Candidate Chunks
          |
    AdaptiveRetriever  (this package -- conservative, bounded re-ranking)
          |
    Context Selection (app.engine.knowledge.context.ContextBuilder, unmodified)
          |
    Agent Execution
          |
    Stage 4E Objective Verification (unmodified)
          |
    RetrievalFeedback  (verified outcomes only)
          |
    RetrievalPassport  (per-chunk, recomputable from raw feedback)
          |
    Future retrieval improves (fed back into AdaptiveRetriever)

**Learns only from objective verified outcomes.** Only
`VerificationStatus.PASSED` ever counts as verified retrieval success
anywhere in this package -- never model self-rating, chain-of-thought,
subjective "this context was useful" text, unverified execution success,
or arbitrary feedback text. See `feedback.py`'s module docstring.

**Wraps Stage 6A; never replaces or bypasses it.** `AdaptiveRetriever`
always calls Stage 6A's own `search()` for the authoritative candidate
set and only re-scores/re-sorts within it. See `reranking.py`.

**Explicit, conservative, opt-in.** `AdaptiveRetrievalPolicy.enabled`
defaults to `False`; benchmark evidence is off by default and never
blended with production evidence. See `policy.py`/`scoring.py`.

**Storage-neutral.** `RetrievalFeedbackRepository` is a Protocol; only an
in-memory implementation exists here. No SQLAlchemy model, migration,
network call, or credential exists anywhere in this package -- real
persistence is a separate, later integration.

Does not implement: exploration/bandits/RL, database persistence, Router
wiring, Nemotron integration, or any change to Stage 5/6A/7A/7B/Router
internals.
"""

from app.engine.adaptive_retrieval.errors import (
    AdaptiveRetrievalError,
    MalformedAdaptiveRetrievalPolicyError,
    MalformedRetrievalFeedbackError,
    MalformedRetrievalObservationError,
    RetrievalFeedbackConflictError,
)
from app.engine.adaptive_retrieval.feedback import (
    InMemoryRetrievalFeedbackRepository,
    RetrievalFeedback,
    RetrievalFeedbackRepository,
)
from app.engine.adaptive_retrieval.models import RetrievalObservation, compute_query_fingerprint
from app.engine.adaptive_retrieval.passport import (
    RetrievalBucket,
    RetrievalPassport,
    rebuild_all_retrieval_passports,
    rebuild_retrieval_passport,
)
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever, RankedResult, results_only
from app.engine.adaptive_retrieval.scoring import (
    SelectedEvidence,
    bounded_adjustment,
    select_evidence,
)

__all__ = [
    "AdaptiveRetrievalError",
    "AdaptiveRetrievalPolicy",
    "AdaptiveRetriever",
    "InMemoryRetrievalFeedbackRepository",
    "MalformedAdaptiveRetrievalPolicyError",
    "MalformedRetrievalFeedbackError",
    "MalformedRetrievalObservationError",
    "RankedResult",
    "RetrievalBucket",
    "RetrievalFeedback",
    "RetrievalFeedbackConflictError",
    "RetrievalFeedbackRepository",
    "RetrievalObservation",
    "RetrievalPassport",
    "SelectedEvidence",
    "bounded_adjustment",
    "compute_query_fingerprint",
    "rebuild_all_retrieval_passports",
    "rebuild_retrieval_passport",
    "results_only",
    "select_evidence",
]
