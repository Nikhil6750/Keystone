"""A controllable `RoutingEvidenceProvider` fake for routing tests."""

from dataclasses import dataclass, field

from app.contracts.passports import AgentPassportMetricBucket


@dataclass
class FakeEvidenceProvider:
    """Returns pre-configured evidence buckets, or `None`/no data when unconfigured."""

    overall: dict[str, AgentPassportMetricBucket] = field(default_factory=dict)
    by_task_type: dict[tuple[str, str], AgentPassportMetricBucket] = field(default_factory=dict)
    by_repository: dict[tuple[str, str], AgentPassportMetricBucket] = field(default_factory=dict)
    cost_usd: dict[str, float] = field(default_factory=dict)

    def overall_metrics(self, agent_type: str) -> AgentPassportMetricBucket | None:
        return self.overall.get(agent_type)

    def task_type_metrics(
        self, agent_type: str, task_type: str
    ) -> AgentPassportMetricBucket | None:
        return self.by_task_type.get((agent_type, task_type))

    def repository_metrics(
        self, agent_type: str, repository_id: str
    ) -> AgentPassportMetricBucket | None:
        return self.by_repository.get((agent_type, repository_id))

    def cost_usd_estimate(self, agent_type: str) -> float | None:
        return self.cost_usd.get(agent_type)
