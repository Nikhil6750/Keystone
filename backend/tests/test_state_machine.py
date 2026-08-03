"""Tests for workflow and step state-transition rules."""

from datetime import UTC, datetime
from itertools import product

import pytest

from app.engine.state_machine import (
    STEP_TRANSITIONS,
    WORKFLOW_TRANSITIONS,
    InvalidStateTransition,
    transition_step,
    transition_workflow,
)
from app.models.enums import StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep


def _workflow(status: WorkflowStatus) -> Workflow:
    return Workflow(
        name="demo",
        input_payload={},
        status=status,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _step(status: StepStatus) -> WorkflowStep:
    return WorkflowStep(
        name="demo-step",
        position=0,
        agent_type="mock",
        input_payload={},
        status=status,
        max_attempts=3,
        attempt_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


ALL_WORKFLOW_PAIRS = list(product(WorkflowStatus, WorkflowStatus))
ALLOWED_WORKFLOW_PAIRS = [
    (start, end) for start, ends in WORKFLOW_TRANSITIONS.items() for end in ends
]
PROHIBITED_WORKFLOW_PAIRS = [
    pair for pair in ALL_WORKFLOW_PAIRS if pair not in ALLOWED_WORKFLOW_PAIRS
]

ALL_STEP_PAIRS = list(product(StepStatus, StepStatus))
ALLOWED_STEP_PAIRS = [(start, end) for start, ends in STEP_TRANSITIONS.items() for end in ends]
PROHIBITED_STEP_PAIRS = [pair for pair in ALL_STEP_PAIRS if pair not in ALLOWED_STEP_PAIRS]


@pytest.mark.parametrize(("start", "end"), ALLOWED_WORKFLOW_PAIRS)
def test_allowed_workflow_transition_succeeds(start: WorkflowStatus, end: WorkflowStatus) -> None:
    workflow = _workflow(start)
    result = transition_workflow(workflow, end)
    assert result.status == end


@pytest.mark.parametrize(("start", "end"), PROHIBITED_WORKFLOW_PAIRS)
def test_prohibited_workflow_transition_fails(start: WorkflowStatus, end: WorkflowStatus) -> None:
    workflow = _workflow(start)
    with pytest.raises(InvalidStateTransition):
        transition_workflow(workflow, end)
    assert workflow.status == start


def test_terminal_workflow_states_reject_further_transitions() -> None:
    terminal_states = (
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.COMPENSATED,
        WorkflowStatus.CANCELLED,
    )
    for terminal in terminal_states:
        for target in WorkflowStatus:
            workflow = _workflow(terminal)
            with pytest.raises(InvalidStateTransition):
                transition_workflow(workflow, target)


def test_invalid_workflow_transition_leaves_workflow_unchanged() -> None:
    workflow = _workflow(WorkflowStatus.PENDING)
    original_version = workflow.version
    original_updated_at = workflow.updated_at

    with pytest.raises(InvalidStateTransition):
        transition_workflow(workflow, WorkflowStatus.SUCCEEDED)

    assert workflow.status == WorkflowStatus.PENDING
    assert workflow.version == original_version
    assert workflow.updated_at == original_updated_at
    assert workflow.completed_at is None


def test_workflow_version_increments_only_after_successful_transition() -> None:
    workflow = _workflow(WorkflowStatus.PENDING)
    assert workflow.version == 1

    transition_workflow(workflow, WorkflowStatus.RUNNING)
    assert workflow.version == 2

    with pytest.raises(InvalidStateTransition):
        transition_workflow(workflow, WorkflowStatus.PENDING)
    assert workflow.version == 2


def test_workflow_timestamps_are_updated_correctly() -> None:
    workflow = _workflow(WorkflowStatus.PENDING)
    assert workflow.started_at is None
    assert workflow.completed_at is None

    transition_workflow(workflow, WorkflowStatus.RUNNING)
    assert workflow.started_at is not None
    started_at = workflow.started_at
    assert workflow.completed_at is None

    transition_workflow(workflow, WorkflowStatus.FAILED)
    assert workflow.started_at == started_at
    assert workflow.completed_at is not None


@pytest.mark.parametrize(("start", "end"), ALLOWED_STEP_PAIRS)
def test_allowed_step_transition_succeeds(start: StepStatus, end: StepStatus) -> None:
    step = _step(start)
    result = transition_step(step, end)
    assert result.status == end


@pytest.mark.parametrize(("start", "end"), PROHIBITED_STEP_PAIRS)
def test_prohibited_step_transition_fails(start: StepStatus, end: StepStatus) -> None:
    step = _step(start)
    with pytest.raises(InvalidStateTransition):
        transition_step(step, end)
    assert step.status == start


def test_invalid_step_transition_leaves_step_unchanged() -> None:
    step = _step(StepStatus.PENDING)
    original_updated_at = step.updated_at

    with pytest.raises(InvalidStateTransition):
        transition_step(step, StepStatus.SUCCEEDED)

    assert step.status == StepStatus.PENDING
    assert step.updated_at == original_updated_at


def test_step_timestamps_are_updated_correctly() -> None:
    step = _step(StepStatus.PENDING)
    assert step.started_at is None

    transition_step(step, StepStatus.RUNNING)
    assert step.started_at is not None
    started_at = step.started_at

    transition_step(step, StepStatus.RETRYING)
    assert step.started_at == started_at
    assert step.completed_at is None

    transition_step(step, StepStatus.RUNNING)
    assert step.started_at == started_at

    transition_step(step, StepStatus.SUCCEEDED)
    assert step.completed_at is not None
