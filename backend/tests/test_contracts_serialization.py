"""Cross-cutting serialization-safety tests for every contract model.

Confirms every contract model can build a representative instance, dump to
JSON, and round-trip back to an equal model — and that no model anywhere in
the contract layer defines a credential-shaped field.
"""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.contracts.adapter import (
    AgentDescriptor,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentUsage,
    RepositoryMetadata,
)
from app.contracts.benchmark import BenchmarkDefinition, BenchmarkResult, BenchmarkTask
from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.explainability import Confidence, DecisionTrace, DecisionType, EvidenceItem
from app.contracts.knowledge import KnowledgeDocument, KnowledgeSearchResult
from app.contracts.passports import AgentPassport, AgentPassportMetricBucket
from app.contracts.planning import ExpectedOutcome, PlanningRequest, TaskSpec, WorkflowPlan
from app.contracts.routing import (
    RoutingCandidateScore,
    RoutingConstraints,
    RoutingDecision,
    RoutingRequest,
)
from app.contracts.schema_export import CONTRACT_MODELS
from app.contracts.verification import VerificationEvidence, VerificationResult, VerificationStatus
from app.contracts.workflow import (
    WorkflowDefinition,
    WorkflowExecutionEvent,
    WorkflowStepDefinition,
)

_NOW = datetime.now(UTC)

_SAMPLES: list[BaseModel] = [
    AgentDescriptor(agent_type="demo", display_name="Demo"),
    RepositoryMetadata(repository_id="repo-1", name="keystone"),
    AgentUsage(input_tokens=10, output_tokens=20, cost_usd=0.01),
    AgentExecutionRequest(
        agent_id="demo-1",
        agent_type="demo",
        execution_id="exec-1",
        workflow_id="wf-1",
        step_id="step-1",
        task_type="code_generation",
        timeout_seconds=30.0,
    ),
    AgentExecutionResult(
        agent_id="demo-1",
        agent_type="demo",
        execution_id="exec-1",
        workflow_id="wf-1",
        step_id="step-1",
        status=AgentExecutionStatus.SUCCEEDED,
        output_payload={"ok": True},
    ),
    WorkflowStepDefinition(key="a", name="step-a", agent_type="demo"),
    WorkflowDefinition(
        name="wf", steps=[WorkflowStepDefinition(key="a", name="a", agent_type="demo")]
    ),
    WorkflowExecutionEvent(
        event_id="evt-1",
        workflow_id="wf-1",
        event_type="workflow_created",
        sequence_number=1,
        timestamp=_NOW,
    ),
    RoutingRequest(task_type="code_generation"),
    RoutingConstraints(excluded_agent_types=["codex"], max_cost_usd=1.0),
    RoutingCandidateScore(agent_type="demo", eligible=True, capability_match=True),
    RoutingDecision(
        task_type="code_generation",
        selected_agent_type="demo",
        explanation="only eligible candidate",
        decided_at=_NOW,
    ),
    AgentPassportMetricBucket(),
    AgentPassport(agent_type="demo", updated_at=_NOW),
    KnowledgeDocument(
        document_id="doc-1",
        vault_id="vault-1",
        title="Note",
        relative_path="note.md",
        content_hash="abc123",
        size_bytes=10,
        modified_at=_NOW,
    ),
    KnowledgeSearchResult(
        document_id="doc-1", vault_id="vault-1", title="Note", snippet="...", score=1.0
    ),
    BenchmarkTask(
        task_id="task-1", input_payload={}, evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH
    ),
    BenchmarkDefinition(
        benchmark_id="bench-1",
        name="demo",
        tasks=[
            BenchmarkTask(
                task_id="task-1",
                input_payload={},
                evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
            )
        ],
        candidate_agent_types=["demo"],
        timeout_seconds=10.0,
    ),
    BenchmarkResult(
        benchmark_id="bench-1",
        run_id="run-1",
        agent_type="demo",
        task_id="task-1",
        success=True,
        duration_ms=1.0,
        created_at=_NOW,
    ),
    ExpectedOutcome(evaluator_type=BenchmarkEvaluatorType.UNIT_TEST, criteria={"min_passed": 1}),
    TaskSpec(key="a", name="a", task_type="analysis"),
    WorkflowPlan(
        plan_id="p1",
        goal="build auth",
        tasks=[TaskSpec(key="a", name="a", task_type="analysis")],
        created_at=_NOW,
    ),
    PlanningRequest(goal="build auth"),
    VerificationEvidence(kind="test_run", description="10/10 tests passed", value={"passed": 10}),
    VerificationResult(
        verification_id="v1",
        workflow_id="wf-1",
        status=VerificationStatus.PASSED,
        evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
        created_at=_NOW,
    ),
    EvidenceItem(kind="success_rate", description="90% over 20 runs", value=0.9),
    Confidence(value=0.8, basis="sample_size", sample_size=20),
    DecisionTrace(
        decision_id="d1",
        decision_type=DecisionType.ROUTING,
        subject_id="wf-1",
        summary="selected claude_code",
        created_at=_NOW,
    ),
]

_FORBIDDEN_FIELD_SUBSTRINGS = ("password", "credential", "secret", "access_token", "session_token")


@pytest.mark.parametrize("instance", _SAMPLES, ids=lambda inst: type(inst).__name__)
def test_contract_model_round_trips_through_json(instance: BaseModel) -> None:
    dumped = instance.model_dump_json()
    restored = type(instance).model_validate_json(dumped)
    assert restored == instance


def test_no_contract_model_defines_a_credential_shaped_field() -> None:
    offenders: list[str] = []
    for name, model in CONTRACT_MODELS.items():
        for field_name in model.model_fields:
            lowered = field_name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_SUBSTRINGS):
                offenders.append(f"{name}.{field_name}")
    assert offenders == []


def test_every_sample_model_type_is_registered_for_schema_export() -> None:
    sample_type_names = {type(instance).__name__ for instance in _SAMPLES}
    registered_names = set(CONTRACT_MODELS.keys())
    missing = sample_type_names - registered_names
    assert missing == set(), f"sampled models missing from CONTRACT_MODELS: {missing}"
