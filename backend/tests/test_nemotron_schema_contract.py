"""Tests for `app.integrations.nemotron.schema_contract`: the schema-driven
output contract embedded in the Nemotron system prompt (Stage 8B.1 Part A).

Prefers assertions tied to `ManagerResponse`/`ManagerTaskProposal`/
`ManagerEvidenceRef`'s own `model_fields`/`model_json_schema()` over
fragile hardcoded substring lists, so these tests fail loudly if the
contract text and the real Pydantic models ever drift apart -- exactly the
class of bug this module exists to prevent.
"""

import pytest
from pydantic import ValidationError

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.engine.manager.models import ManagerEvidenceRef, ManagerResponse, ManagerTaskProposal
from app.engine.verification.recovery import RecoveryAction
from app.integrations.nemotron.schema_contract import (
    MANAGER_RESPONSE_CONTRACT,
    build_manager_response_contract,
)


def _field_line(contract: str, field_name: str) -> str:
    """The single contract line describing `field_name`, or raise if absent."""
    for line in contract.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {field_name}:"):
            return stripped
    raise AssertionError(f"no contract line found for field {field_name!r}")


# --- 1. contract contains every real ManagerResponse field name -----------


def test_contract_contains_every_top_level_manager_response_field() -> None:
    for field_name in ManagerResponse.model_fields:
        assert field_name in MANAGER_RESPONSE_CONTRACT, f"missing field: {field_name}"


def test_contract_contains_every_manager_task_proposal_field() -> None:
    for field_name in ManagerTaskProposal.model_fields:
        assert field_name in MANAGER_RESPONSE_CONTRACT, f"missing field: {field_name}"


def test_contract_contains_every_manager_evidence_ref_field() -> None:
    for field_name in ManagerEvidenceRef.model_fields:
        assert field_name in MANAGER_RESPONSE_CONTRACT, f"missing field: {field_name}"


def test_contract_states_return_exactly_one_json_object() -> None:
    assert "Return exactly one JSON object conforming to this schema." in MANAGER_RESPONSE_CONTRACT


# --- 2. nested task proposal requires `key` --------------------------------


def test_key_is_required_in_the_real_schema() -> None:
    schema = ManagerTaskProposal.model_json_schema()
    assert "key" in schema["required"]


def test_contract_marks_key_as_required() -> None:
    line = _field_line(MANAGER_RESPONSE_CONTRACT, "key")
    assert "REQUIRED" in line


def test_contract_marks_description_as_required_on_task_proposal() -> None:
    line = _field_line(MANAGER_RESPONSE_CONTRACT, "description")
    assert "REQUIRED" in line


# --- 3. required_capabilities communicated as an array ---------------------


def test_required_capabilities_is_array_in_the_real_schema() -> None:
    schema = ManagerTaskProposal.model_json_schema()
    assert schema["properties"]["required_capabilities"]["type"] == "array"


def test_contract_communicates_required_capabilities_as_array() -> None:
    line = _field_line(MANAGER_RESPONSE_CONTRACT, "required_capabilities")
    assert "array" in line


# --- 4. evidence_summary communicated as an array --------------------------


def test_evidence_summary_is_array_in_the_real_schema() -> None:
    schema = ManagerResponse.model_json_schema()
    assert schema["properties"]["evidence_summary"]["type"] == "array"


def test_contract_communicates_evidence_summary_as_array() -> None:
    line = _field_line(MANAGER_RESPONSE_CONTRACT, "evidence_summary")
    assert "array" in line


# --- 5. unknown keys remain forbidden --------------------------------------


def test_manager_response_schema_forbids_additional_properties() -> None:
    schema = ManagerResponse.model_json_schema()
    assert schema["additionalProperties"] is False


def test_manager_task_proposal_schema_forbids_additional_properties() -> None:
    schema = ManagerTaskProposal.model_json_schema()
    assert schema["additionalProperties"] is False


def test_contract_states_no_fields_beyond_the_list_are_permitted() -> None:
    assert "No fields beyond exactly this list are permitted" in MANAGER_RESPONSE_CONTRACT


# --- 6. enum values in the contract match the real Pydantic enums ---------


def test_contract_contains_every_agent_capability_value() -> None:
    for capability in AgentCapability:
        assert f'"{capability.value}"' in MANAGER_RESPONSE_CONTRACT


def test_contract_contains_every_benchmark_evaluator_type_value() -> None:
    for evaluator in BenchmarkEvaluatorType:
        assert f'"{evaluator.value}"' in MANAGER_RESPONSE_CONTRACT


def test_contract_contains_every_recovery_action_value() -> None:
    for action in RecoveryAction:
        assert f'"{action.value}"' in MANAGER_RESPONSE_CONTRACT


# --- 7. deterministic generation -------------------------------------------


def test_contract_generation_is_deterministic() -> None:
    results = [build_manager_response_contract() for _ in range(10)]
    assert all(result == results[0] for result in results)


def test_module_constant_matches_a_fresh_call() -> None:
    assert build_manager_response_contract() == MANAGER_RESPONSE_CONTRACT


# --- 8/9. no compatibility aliases added -----------------------------------


def test_no_task_id_alias_added_to_task_proposal_schema() -> None:
    assert "task_id" not in ManagerTaskProposal.model_fields


def test_no_agent_type_alias_added_to_task_proposal_schema() -> None:
    assert "agent_type" not in ManagerTaskProposal.model_fields


def test_task_id_still_rejected_as_extra_field() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal.model_validate({"key": "t1", "description": "d", "task_id": "t1"})


def test_agent_type_still_rejected_as_extra_field() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal.model_validate(
            {"key": "t1", "description": "d", "agent_type": "claude_code"}
        )


def test_contract_explicitly_warns_against_the_observed_incompatible_fields() -> None:
    """The four field names Nemotron actually invented in the certified
    live diagnostic must be named explicitly as forbidden, not just
    implicitly absent."""
    for forbidden_field in ("agent_type", "task_id", "inputs", "expected_outputs"):
        assert forbidden_field in MANAGER_RESPONSE_CONTRACT
    assert "a single string field named 'capability'" in MANAGER_RESPONSE_CONTRACT
