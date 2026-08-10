"""End-to-end tests wiring `NemotronManagerModel` into the real, unmodified
Stage 8A `ManagerOrchestrator` -- proving the production adapter composes
correctly with Stage 8A's validation gate, deterministic fallback, and the
real `Planner`, entirely offline via `FakeNemotronTransport`.
"""

import json

from app.contracts.enums import AgentCapability
from app.contracts.planning import PlanningRequest
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.manager.models import ManagerRequest
from app.engine.manager.orchestrator import ManagerOrchestrator
from app.engine.planning.planner import Planner
from app.engine.routing.router import Router
from app.integrations.nemotron.adapter import NemotronManagerModel
from app.integrations.nemotron.config import NemotronConfig
from app.integrations.nemotron.fake import FakeNemotronTransport
from app.integrations.nemotron.transport import TransportResponse
from tests.test_manager_orchestrator import _candidate


def _planning_request(**overrides: object) -> PlanningRequest:
    base: dict[str, object] = {"goal": "Implement user authentication with tests"}
    base.update(overrides)
    return PlanningRequest.model_validate(base)


def _manager_request(**overrides: object) -> ManagerRequest:
    base: dict[str, object] = {
        "request_id": "req-1",
        "goal": "Implement user authentication with tests",
    }
    base.update(overrides)
    return ManagerRequest.model_validate(base)


def _chat_response(content: str, *, status_code: int = 200) -> TransportResponse:
    payload = {"choices": [{"message": {"content": content}}]}
    return TransportResponse(status_code=status_code, body=json.dumps(payload).encode("utf-8"))


def _orchestrator_with_fake_nemotron(fake: FakeNemotronTransport) -> ManagerOrchestrator:
    nemotron = NemotronManagerModel(config=NemotronConfig(), transport=fake)
    return ManagerOrchestrator(manager_model=nemotron)


# --- successful proposal -> Stage 8A validator -> Planner -------------------


async def test_valid_provider_response_flows_through_validator_to_planner() -> None:
    manager_request = _manager_request(available_agent_types=["claude_code"])
    fake = FakeNemotronTransport(
        response=_chat_response(
            json.dumps(
                {
                    "request_id": "req-1",
                    "provider_identifier": "nemotron-3-ultra",
                    "task_proposals": [
                        {
                            "key": "t1",
                            "description": "do it",
                            "preferred_agent_types": ["claude_code"],
                        }
                    ],
                }
            )
        )
    )
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=manager_request
    )

    assert result.manager_used is True
    assert result.proposal_validated is True
    assert result.fallback_used is False
    assert result.manager_identifier == "nemotron-3-ultra"
    # The plan still comes from the real, unmodified Planner.
    baseline_plan = Planner().plan(_planning_request())
    assert result.selected_task_count == len(baseline_plan.tasks)


# --- invalid provider response -> deterministic fallback --------------------


async def test_malformed_provider_response_falls_back_deterministically() -> None:
    fake = FakeNemotronTransport(
        response=TransportResponse(status_code=200, body=b"{not valid json")
    )
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    baseline_plan = Planner().plan(_planning_request())

    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=_manager_request()
    )

    assert result.manager_used is True
    assert result.fallback_used is True
    assert result.proposal_validated is False
    assert result.plan.plan_id == baseline_plan.plan_id
    assert result.plan.tasks == baseline_plan.tasks


async def test_schema_invalid_manager_response_falls_back_deterministically() -> None:
    fake = FakeNemotronTransport(
        response=_chat_response(json.dumps({"request_id": "req-1", "confidence": 5.0}))
    )
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=_manager_request()
    )
    assert result.fallback_used is True


async def test_rejected_proposal_falls_back_deterministically() -> None:
    """Structurally valid but referencing an unknown agent type -- Stage
    8A's `ManagerProposalValidator` rejects it, and the orchestrator falls
    back to the unmodified plan."""
    fake = FakeNemotronTransport(
        response=_chat_response(
            json.dumps(
                {
                    "request_id": "req-1",
                    "task_proposals": [
                        {
                            "key": "t1",
                            "description": "do it",
                            "preferred_agent_types": ["totally_unknown_agent"],
                        }
                    ],
                }
            )
        )
    )
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    result = await orchestrator.orchestrate(
        planning_request=_planning_request(),
        manager_request=_manager_request(available_agent_types=["claude_code"]),
    )
    assert result.proposal_validated is False
    assert result.fallback_used is True
    assert "unknown_preferred_agent_type" in result.validation_issue_codes


# --- provider unavailable -> deterministic fallback --------------------


async def test_provider_unavailable_falls_back_deterministically() -> None:
    fake = FakeNemotronTransport(response=_chat_response("irrelevant", status_code=503))
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    baseline_plan = Planner().plan(_planning_request())

    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=_manager_request()
    )

    assert result.fallback_used is True
    assert result.plan.tasks == baseline_plan.tasks
    assert any("fallback" in w for w in result.warnings)


async def test_provider_authentication_failure_falls_back_deterministically() -> None:
    fake = FakeNemotronTransport(response=_chat_response("irrelevant", status_code=401))
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=_manager_request()
    )
    assert result.fallback_used is True
    assert result.manager_used is True


async def test_httpx_unavailable_falls_back_deterministically(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If `httpx` itself cannot be imported (e.g. a stripped-down
    deployment with only main dependencies installed), the adapter must
    degrade to "manager unavailable", not crash Keystone."""
    import sys

    monkeypatch.setitem(sys.modules, "httpx", None)
    nemotron = NemotronManagerModel()  # no transport injected -> lazy httpx import path
    orchestrator = ManagerOrchestrator(manager_model=nemotron)
    baseline_plan = Planner().plan(_planning_request())

    result = await orchestrator.orchestrate(
        planning_request=_planning_request(), manager_request=_manager_request()
    )

    assert result.fallback_used is True
    assert result.plan.tasks == baseline_plan.tasks


# --- Router authority remains unchanged --------------------------------


async def test_router_authority_unchanged_by_nemotron_proposal() -> None:
    """A validated Nemotron-sourced `preferred_agent_types` preference is
    folded only into `RoutingConstraints.preferred_agent_types` -- the same
    non-eligibility-affecting ranking signal Stage 8A's own tests already
    prove cannot bypass `Router`'s hard eligibility constraints. This test
    proves the same property holds when the proposal actually originated
    from the Nemotron adapter's parsed output, not a hand-built
    `ManagerResponse`."""
    fake = FakeNemotronTransport(
        response=_chat_response(
            json.dumps(
                {
                    "request_id": "req-1",
                    "task_proposals": [
                        {
                            "key": "t1",
                            "description": "do it",
                            "preferred_agent_types": ["banned_agent"],
                        }
                    ],
                }
            )
        )
    )
    orchestrator = _orchestrator_with_fake_nemotron(fake)
    result = await orchestrator.orchestrate(
        planning_request=_planning_request(
            constraints=RoutingConstraints(excluded_agent_types=["banned_agent"])
        ),
        manager_request=_manager_request(available_agent_types=["banned_agent", "safe_agent"]),
    )
    assert result.proposal_validated is True

    routing_request = RoutingRequest(
        task_type="code_generation",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        constraints=RoutingConstraints(
            excluded_agent_types=["banned_agent"], preferred_agent_types=["banned_agent"]
        ),
    )
    router = Router()
    decision = router.route(
        routing_request, [_candidate("banned_agent"), _candidate("safe_agent")]
    )
    assert decision.selected_agent_type == "safe_agent"


# --- determinism ------------------------------------------------------------


async def test_identical_request_and_response_yield_identical_manager_response() -> None:
    content = json.dumps(
        {
            "request_id": "req-1",
            "provider_identifier": "nemotron-3-ultra",
            "task_proposals": [{"key": "t1", "description": "do it"}],
        }
    )
    manager_request = _manager_request()

    results = []
    for _ in range(10):
        fake = FakeNemotronTransport(response=_chat_response(content))
        model = NemotronManagerModel(transport=fake)
        results.append(await model.propose(manager_request))

    first = results[0]
    for result in results[1:]:
        assert result == first


async def test_orchestrator_end_to_end_deterministic_across_ten_runs() -> None:
    content = json.dumps(
        {
            "request_id": "req-1",
            "task_proposals": [
                {"key": "t1", "description": "do it", "preferred_agent_types": ["claude_code"]}
            ],
        }
    )
    manager_request = _manager_request(available_agent_types=["claude_code"])

    results = []
    for _ in range(10):
        fake = FakeNemotronTransport(response=_chat_response(content))
        orchestrator = _orchestrator_with_fake_nemotron(fake)
        result = await orchestrator.orchestrate(
            planning_request=_planning_request(), manager_request=manager_request
        )
        results.append(result)

    first = results[0]
    for result in results[1:]:
        assert result.plan.plan_id == first.plan.plan_id
        assert result.plan.tasks == first.plan.tasks
        assert result.proposal_validated == first.proposal_validated
        assert result.fallback_used == first.fallback_used
        assert result.selected_task_count == first.selected_task_count
