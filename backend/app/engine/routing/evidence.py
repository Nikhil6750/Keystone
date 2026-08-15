"""The seam through which the router queries historical execution evidence.

No implementation here computes real evidence — `NullEvidenceProvider`
always reports "no data," used as the router's default and throughout its
tests. Stage 5's agent-passport aggregation is expected to provide the real
implementation of this same protocol without any change to the router,
scorer, or their tests.

`cost_usd_estimate` has no backing data source yet: no contract in
`app.contracts` currently tracks a per-agent, per-execution cost history
(`AgentPassportMetricBucket` has no cost field). It is defined here now so
`RoutingConstraints.max_cost_usd`/the scorer's cost factor have a stable
seam to call — every implementation, including `NullEvidenceProvider`,
reports `None` ("no credible cost evidence") until Stage 5 wires up real
cost aggregation, and the router treats that `None` exactly like any other
missing evidence: never assumed to be zero or compliant.
"""

from typing import Protocol

from app.contracts.passports import AgentPassportMetricBucket


class RoutingEvidenceProvider(Protocol):
    """Read-only historical-evidence lookups, keyed by agent type."""

    def overall_metrics(self, agent_type: str) -> AgentPassportMetricBucket | None:
        """All-time execution evidence for `agent_type`, or `None` if there is none."""
        ...

    def task_type_metrics(
        self, agent_type: str, task_type: str
    ) -> AgentPassportMetricBucket | None:
        """Execution evidence for `agent_type` on `task_type` specifically."""
        ...

    def repository_metrics(
        self, agent_type: str, repository_id: str
    ) -> AgentPassportMetricBucket | None:
        """Execution evidence for `agent_type` on `repository_id` specifically."""
        ...

    def cost_usd_estimate(self, agent_type: str) -> float | None:
        """A credible estimated USD cost for one execution by `agent_type`,
        or `None` if there is no measured cost evidence."""
        ...


class NullEvidenceProvider:
    """Reports no historical data for every agent. The router's default."""

    def overall_metrics(self, agent_type: str) -> AgentPassportMetricBucket | None:
        return None

    def task_type_metrics(
        self, agent_type: str, task_type: str
    ) -> AgentPassportMetricBucket | None:
        return None

    def repository_metrics(
        self, agent_type: str, repository_id: str
    ) -> AgentPassportMetricBucket | None:
        return None

    def cost_usd_estimate(self, agent_type: str) -> float | None:
        return None


__all__ = ["NullEvidenceProvider", "RoutingEvidenceProvider"]
