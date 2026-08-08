"""`PassportEvidenceProvider`: the first real implementation of the
existing `RoutingEvidenceProvider` Protocol (`app.engine.routing.evidence`)
-- every implementation before Stage 5A was either `NullEvidenceProvider`
(always reports "no data") or a test fake.

Duck-types the Protocol structurally; no explicit inheritance is required
or declared. `Router`/`app.engine.routing.scorer` are never imported here
and are never modified by Stage 5A -- this module only *supplies* evidence
in the exact shape they already consume, via `Router(evidence=...)`.

A point-in-time snapshot, like `CandidateAgent`: it answers every query
from the `LearningPassport`s supplied at construction, never re-aggregating
or re-querying anything live.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.contracts.passports import AgentPassportMetricBucket
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport, rebuild_all_passports


@dataclass(frozen=True)
class PassportEvidenceProvider:
    """Serves `RoutingEvidenceProvider` evidence from pre-built
    `LearningPassport`s, keyed by `agent_type`."""

    passports: dict[str, LearningPassport] = field(default_factory=dict)

    def overall_metrics(self, agent_type: str) -> AgentPassportMetricBucket | None:
        """All-time execution evidence for `agent_type`, or `None` if there
        is no passport for it at all."""
        passport = self.passports.get(agent_type)
        return passport.overall_metrics if passport is not None else None

    def task_type_metrics(
        self, agent_type: str, task_type: str
    ) -> AgentPassportMetricBucket | None:
        passport = self.passports.get(agent_type)
        if passport is None:
            return None
        return passport.passport.task_type_metrics.get(task_type)

    def repository_metrics(
        self, agent_type: str, repository_id: str
    ) -> AgentPassportMetricBucket | None:
        passport = self.passports.get(agent_type)
        if passport is None:
            return None
        return passport.passport.repository_metrics.get(repository_id)

    def cost_usd_estimate(self, agent_type: str) -> float | None:
        """Only a *real* cost estimate -- the average of actually-known
        `LearningEvent.cost_usd` values that fed this agent's passport, or
        `None` when no execution ever reported a real cost. Never
        fabricated, never defaulted to `0.0`, exactly like
        `NullEvidenceProvider`'s own documented "no credible cost evidence"
        contract (`app.engine.routing.evidence`)."""
        passport = self.passports.get(agent_type)
        return passport.known_cost_usd_average if passport is not None else None


def build_passport_evidence_provider(
    events: list[LearningEvent], *, updated_at: datetime
) -> PassportEvidenceProvider:
    """The full Stage 5A pipeline in one call: raw `LearningEvent`s ->
    `LearningPassport`s (one per `agent_type`) -> a ready-to-use
    `PassportEvidenceProvider` for `Router(evidence=...)`."""
    passports = rebuild_all_passports(events, updated_at=updated_at)
    return PassportEvidenceProvider(passports=passports)


__all__ = ["PassportEvidenceProvider", "build_passport_evidence_provider"]
