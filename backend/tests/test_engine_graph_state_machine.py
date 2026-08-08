"""Tests for the graph scheduler's validated status-transition tables."""

import pytest

from app.engine.workflow.state_machine import (
    InvalidGraphStateTransition,
    transition_graph_step,
    transition_graph_workflow,
)
from app.engine.workflow.status import GraphStepStatus, GraphWorkflowStatus


def test_workflow_pending_to_running_is_allowed() -> None:
    assert (
        transition_graph_workflow(GraphWorkflowStatus.PENDING, GraphWorkflowStatus.RUNNING)
        is GraphWorkflowStatus.RUNNING
    )


def test_workflow_running_to_succeeded_is_allowed() -> None:
    assert (
        transition_graph_workflow(GraphWorkflowStatus.RUNNING, GraphWorkflowStatus.SUCCEEDED)
        is GraphWorkflowStatus.SUCCEEDED
    )


def test_workflow_succeeded_has_no_outgoing_transitions() -> None:
    with pytest.raises(InvalidGraphStateTransition):
        transition_graph_workflow(GraphWorkflowStatus.SUCCEEDED, GraphWorkflowStatus.RUNNING)


def test_workflow_cannot_go_from_succeeded_to_cancelled() -> None:
    with pytest.raises(InvalidGraphStateTransition):
        transition_graph_workflow(GraphWorkflowStatus.SUCCEEDED, GraphWorkflowStatus.CANCELLED)


def test_workflow_cancelling_only_leads_to_cancelled() -> None:
    assert (
        transition_graph_workflow(GraphWorkflowStatus.CANCELLING, GraphWorkflowStatus.CANCELLED)
        is GraphWorkflowStatus.CANCELLED
    )
    with pytest.raises(InvalidGraphStateTransition):
        transition_graph_workflow(GraphWorkflowStatus.CANCELLING, GraphWorkflowStatus.SUCCEEDED)


def test_step_pending_to_ready_to_running_to_succeeded() -> None:
    assert (
        transition_graph_step(GraphStepStatus.PENDING, GraphStepStatus.READY)
        is GraphStepStatus.READY
    )
    assert (
        transition_graph_step(GraphStepStatus.READY, GraphStepStatus.RUNNING)
        is GraphStepStatus.RUNNING
    )
    assert (
        transition_graph_step(GraphStepStatus.RUNNING, GraphStepStatus.SUCCEEDED)
        is GraphStepStatus.SUCCEEDED
    )


def test_step_running_can_retry() -> None:
    assert (
        transition_graph_step(GraphStepStatus.RUNNING, GraphStepStatus.RETRYING)
        is GraphStepStatus.RETRYING
    )
    assert (
        transition_graph_step(GraphStepStatus.RETRYING, GraphStepStatus.RUNNING)
        is GraphStepStatus.RUNNING
    )


def test_step_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in (
        GraphStepStatus.SUCCEEDED,
        GraphStepStatus.FAILED,
        GraphStepStatus.SKIPPED,
        GraphStepStatus.CANCELLED,
    ):
        with pytest.raises(InvalidGraphStateTransition):
            transition_graph_step(terminal, GraphStepStatus.RUNNING)


def test_step_cannot_skip_directly_from_running() -> None:
    with pytest.raises(InvalidGraphStateTransition):
        transition_graph_step(GraphStepStatus.RUNNING, GraphStepStatus.SKIPPED)


def test_step_pending_can_be_skipped_directly() -> None:
    assert (
        transition_graph_step(GraphStepStatus.PENDING, GraphStepStatus.SKIPPED)
        is GraphStepStatus.SKIPPED
    )
