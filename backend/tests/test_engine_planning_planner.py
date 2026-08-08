"""Comprehensive integration and determinism tests for app.engine.planning.planner."""

import pytest

from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability
from app.contracts.knowledge import KnowledgeSearchResult
from app.contracts.planning import PlanningRequest, WorkflowPlan
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.planning.planner import Planner, plan_workflow
from app.engine.routing.request_builder import build_routing_request


@pytest.fixture
def planner() -> Planner:
    return Planner()


def test_plan_feature_implementation(planner: Planner) -> None:
    req = PlanningRequest(
        goal="Build authentication for this repository",
        repository=RepositoryMetadata(name="keystone", languages=["python"]),
    )
    plan = planner.plan(req)

    assert isinstance(plan, WorkflowPlan)
    assert plan.plan_id.startswith("plan_")
    assert plan.goal == req.goal
    assert plan.metadata["plan_category"] == "feature_implementation"
    assert len(plan.tasks) > 0

    # Verify task ordering and DAG completeness
    keys = [t.key for t in plan.tasks]
    assert keys[0] == "analyze_repository"
    assert keys[-1] == "final_validation"


def test_provider_neutrality(planner: Planner) -> None:
    """Verify generated tasks contain no agent_type and no provider names."""
    req = PlanningRequest(goal="Implement user authentication module with tests")
    plan = planner.plan(req)

    prohibited = ["claude", "codex", "gemini", "nemotron", "openai", "anthropic"]

    for task in plan.tasks:
        # TaskSpec has no agent_type
        assert not hasattr(task, "agent_type")

        # Verify no provider names in task fields or payload values
        dump_str = task.model_dump_json().lower()
        for p in prohibited:
            assert p not in dump_str, f"Provider name '{p}' leaked in task '{task.key}'"


def test_task_spec_to_routing_request_compatibility(planner: Planner) -> None:
    """Verify generated TaskSpecs pass cleanly into Stage 4B build_routing_request."""
    constraints = RoutingConstraints(max_cost_usd=1.5, max_latency_ms=5000.0)
    repo = RepositoryMetadata(name="keystone", languages=["python"])
    req = PlanningRequest(
        goal="Fix bug in authentication token verification",
        repository=repo,
        constraints=constraints,
    )
    plan = planner.plan(req)

    for task in plan.tasks:
        routing_req = build_routing_request(
            task,
            constraints=req.constraints,
            repository=req.repository,
        )
        assert isinstance(routing_req, RoutingRequest)
        assert routing_req.task_type == task.task_type
        assert routing_req.required_capabilities == list(task.required_capabilities)
        assert routing_req.repository == repo
        assert routing_req.constraints == constraints
        # Provider selection MUST NOT happen during building
        assert routing_req.candidate_agent_types is None
        assert routing_req.manual_override_agent_type is None


def test_20_run_semantic_determinism(planner: Planner) -> None:
    """Verify 20 repeated runs on the same PlanningRequest produce identical semantic WorkflowPlans.

    Excludes operational creation timestamp `created_at` from comparison while asserting
    exact equality of plan_id, goal, tasks, dependencies, capabilities, and metadata.
    """
    req = PlanningRequest(
        goal="Refactor database connection pool to eliminate memory leaks",
        repository=RepositoryMetadata(name="keystone-backend"),
        available_capabilities=[
            AgentCapability.GENERAL_REASONING,
            AgentCapability.PLANNING,
            AgentCapability.REFACTORING,
            AgentCapability.TEST_GENERATION,
            AgentCapability.TEST_EXECUTION,
        ],
    )

    baseline_plan = planner.plan(req)
    baseline_semantic = baseline_plan.model_dump(exclude={"created_at"})

    for i in range(20):
        run_plan = planner.plan(req)
        assert run_plan.plan_id == baseline_plan.plan_id, f"Failed plan_id determinism on run {i}"
        assert (
            run_plan.model_dump(exclude={"created_at"}) == baseline_semantic
        ), f"Semantic plan mismatch on run {i}"
        assert run_plan.created_at is not None


def test_knowledge_context_handling_privacy(planner: Planner) -> None:
    """Verify knowledge context title/count is stored safely without path or content leakage."""
    knowledge = [
        KnowledgeSearchResult(
            document_id="doc_123",
            vault_id="vault_456",
            title="Auth Design Doc",
            snippet="Use JWT tokens with RS256 signing secret key secret_12345.",
            score=0.95,
        )
    ]
    req = PlanningRequest(
        goal="Implement JWT authentication",
        knowledge_context=knowledge,
    )
    plan = planner.plan(req)

    assert plan.metadata.get("knowledge_context_count") == 1
    assert "Auth Design Doc" in plan.metadata.get("knowledge_context_titles", [])

    # Verify no raw snippets, secrets, or file paths are stored in plan or task payloads
    plan_dump = plan.model_dump_json()
    assert "secret_12345" not in plan_dump
    assert "vault_456" not in plan_dump


def test_blank_goal_rejected() -> None:
    """Verify empty/blank goals are rejected by PlanningRequest contract validation."""
    with pytest.raises(ValueError, match="goal must not be empty"):
        PlanningRequest(goal="   ")


def test_unsupported_goal_fallback(planner: Planner) -> None:
    """Verify generic/unrecognized goals fall back gracefully to generic_task plan."""
    req = PlanningRequest(goal="Xylophone quantum entanglement zzz 12345")
    plan = planner.plan(req)
    assert plan.metadata["plan_category"] == "generic_task"
    assert len(plan.tasks) > 0


def test_minimal_request_no_repo(planner: Planner) -> None:
    """Verify request with no repository metadata functions correctly."""
    req = PlanningRequest(goal="Write docs for API endpoints")
    plan = planner.plan(req)
    assert plan.repository is None
    assert plan.metadata["plan_category"] == "documentation"


def test_empty_available_capabilities(planner: Planner) -> None:
    """Verify empty available_capabilities does not crash or corrupt planning."""
    req = PlanningRequest(
        goal="Run code review on pull request",
        available_capabilities=[],
    )
    plan = planner.plan(req)
    assert plan.metadata["plan_category"] == "code_review"
    assert len(plan.tasks) > 0


def test_case_and_punctuation_normalization(planner: Planner) -> None:
    """Verify goal case/punctuation variations produce equivalent plans."""
    req1 = PlanningRequest(goal="Fix bug in auth!")
    req2 = PlanningRequest(goal="FIX  BUG  IN  AUTH???")

    plan1 = planner.plan(req1)
    plan2 = planner.plan(req2)

    assert plan1.metadata["plan_category"] == plan2.metadata["plan_category"]
    assert plan1.metadata["complexity_tier"] == plan2.metadata["complexity_tier"]
    assert [t.key for t in plan1.tasks] == [t.key for t in plan2.tasks]


def test_public_helper_plan_workflow() -> None:
    req = PlanningRequest(goal="Perform security audit of API")
    plan = plan_workflow(req)
    assert isinstance(plan, WorkflowPlan)
    assert plan.metadata["plan_category"] == "security_review"
