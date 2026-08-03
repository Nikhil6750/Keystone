"""Tests for the workflow execution context."""

from app.engine.context import ExecutionContext


def test_context_begins_with_workflow_input() -> None:
    context = ExecutionContext(workflow_id="wf-1", workflow_input={"goal": "demo"})

    assert context.workflow_input == {"goal": "demo"}
    assert context.previous_step_outputs == {}


def test_successful_step_outputs_are_added_in_order() -> None:
    context = ExecutionContext(workflow_id="wf-1", workflow_input={})

    context = context.with_step_output("step-1", {"a": 1})
    context = context.with_step_output("step-2", {"b": 2})

    assert list(context.previous_step_outputs.keys()) == ["step-1", "step-2"]
    assert context.previous_step_outputs == {"step-1": {"a": 1}, "step-2": {"b": 2}}


def test_persisted_input_dict_is_not_mutated() -> None:
    original_input = {"goal": "demo"}
    context = ExecutionContext(workflow_id="wf-1", workflow_input=original_input)

    context.with_step_output("step-1", {"a": 1})

    assert original_input == {"goal": "demo"}
    assert context.previous_step_outputs == {}


def test_duplicate_step_names_do_not_overwrite_outputs_because_ids_are_stable() -> None:
    context = ExecutionContext(workflow_id="wf-1", workflow_input={})

    context = context.with_step_output("step-id-1", {"name": "duplicate", "value": 1})
    context = context.with_step_output("step-id-2", {"name": "duplicate", "value": 2})

    assert context.previous_step_outputs["step-id-1"]["value"] == 1
    assert context.previous_step_outputs["step-id-2"]["value"] == 2
