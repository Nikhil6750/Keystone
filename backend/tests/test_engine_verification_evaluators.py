"""Tests for `app.engine.verification.evaluators` and `.registry`: every
currently supported `BenchmarkEvaluatorType`, invalid/malformed inputs,
deterministic output, and the safe execution boundary (no evaluator ever
executes a process)."""

import pytest

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.verification import VerificationStatus
from app.engine.verification.errors import (
    CommandExecutionNotConfiguredError,
    MalformedExpectedOutcomeError,
    UnsafeEvidenceError,
    UnsupportedEvaluatorError,
)
from app.engine.verification.evaluators import (
    CommandSpec,
    NullCommandExecutor,
    ObservedOutcome,
    evaluate_build,
    evaluate_exact_match,
    evaluate_exit_code,
    evaluate_file_diff,
    evaluate_human_reviewed,
    evaluate_json_schema,
    evaluate_lint,
    evaluate_regex,
    evaluate_type_check,
    evaluate_unit_test,
)
from app.engine.verification.registry import EVALUATORS, get_evaluator


def test_registry_covers_every_benchmark_evaluator_type() -> None:
    assert set(EVALUATORS) == set(BenchmarkEvaluatorType)


def test_get_evaluator_raises_for_unsupported_type() -> None:
    with pytest.raises(UnsupportedEvaluatorError):
        get_evaluator("totally_unsupported_type")  # type: ignore[arg-type]


# --- exact_match ----------------------------------------------------------------


def test_exact_match_passes_on_identical_output() -> None:
    outcome = evaluate_exact_match({"expected": "hello"}, ObservedOutcome({"output": "hello"}))
    assert outcome.status is VerificationStatus.PASSED


def test_exact_match_fails_on_different_output() -> None:
    outcome = evaluate_exact_match({"expected": "hello"}, ObservedOutcome({"output": "world"}))
    assert outcome.status is VerificationStatus.FAILED
    assert outcome.failure_reason


def test_exact_match_inconclusive_when_output_missing() -> None:
    outcome = evaluate_exact_match({"expected": "hello"}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_exact_match_raises_on_malformed_criteria() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_exact_match({}, ObservedOutcome({"output": "hello"}))


# --- json_schema ------------------------------------------------------------------


def test_json_schema_passes_on_matching_structure() -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    outcome = evaluate_json_schema(
        {"schema": schema}, ObservedOutcome({"output": {"name": "codex"}})
    )
    assert outcome.status is VerificationStatus.PASSED


def test_json_schema_fails_on_missing_required_property() -> None:
    schema = {"type": "object", "required": ["name"]}
    outcome = evaluate_json_schema({"schema": schema}, ObservedOutcome({"output": {}}))
    assert outcome.status is VerificationStatus.FAILED
    assert "name" in (outcome.failure_reason or "")


def test_json_schema_fails_on_wrong_type() -> None:
    schema = {"type": "array"}
    outcome = evaluate_json_schema({"schema": schema}, ObservedOutcome({"output": {"a": 1}}))
    assert outcome.status is VerificationStatus.FAILED


def test_json_schema_raises_on_malformed_criteria() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_json_schema({}, ObservedOutcome({"output": {}}))


def test_json_schema_inconclusive_when_output_missing() -> None:
    outcome = evaluate_json_schema({"schema": {"type": "object"}}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


# --- regex --------------------------------------------------------------------------


def test_regex_passes_on_match() -> None:
    outcome = evaluate_regex(
        {"pattern": r"\d+ passed"}, ObservedOutcome({"output": "12 passed, 0 failed"})
    )
    assert outcome.status is VerificationStatus.PASSED


def test_regex_fails_on_no_match() -> None:
    outcome = evaluate_regex({"pattern": r"^ERROR"}, ObservedOutcome({"output": "all good"}))
    assert outcome.status is VerificationStatus.FAILED


def test_regex_raises_on_invalid_pattern() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_regex({"pattern": "(unclosed"}, ObservedOutcome({"output": "x"}))


def test_regex_raises_on_missing_pattern() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_regex({}, ObservedOutcome({"output": "x"}))


def test_regex_inconclusive_when_output_missing() -> None:
    outcome = evaluate_regex({"pattern": "x"}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


# --- exit_code / build ---------------------------------------------------------------


def test_exit_code_passes_when_matching_default_zero() -> None:
    outcome = evaluate_exit_code({}, ObservedOutcome({"exit_code": 0}))
    assert outcome.status is VerificationStatus.PASSED


def test_exit_code_fails_when_nonzero() -> None:
    outcome = evaluate_exit_code({}, ObservedOutcome({"exit_code": 1}))
    assert outcome.status is VerificationStatus.FAILED


def test_exit_code_inconclusive_when_missing() -> None:
    outcome = evaluate_exit_code({}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_exit_code_inconclusive_when_malformed_type() -> None:
    outcome = evaluate_exit_code({}, ObservedOutcome({"exit_code": "0"}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_exit_code_raises_on_malformed_criteria() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_exit_code({"expected_exit_code": "zero"}, ObservedOutcome({"exit_code": 0}))


def test_build_uses_same_semantics_as_exit_code() -> None:
    assert evaluate_build({}, ObservedOutcome({"exit_code": 0})).status is VerificationStatus.PASSED
    assert evaluate_build({}, ObservedOutcome({"exit_code": 2})).status is VerificationStatus.FAILED


# --- lint / type_check ----------------------------------------------------------------


def test_lint_passes_within_threshold() -> None:
    outcome = evaluate_lint(
        {"max_violations": 3}, ObservedOutcome({"exit_code": 0, "violation_count": 2})
    )
    assert outcome.status is VerificationStatus.PASSED


def test_lint_fails_above_threshold() -> None:
    outcome = evaluate_lint(
        {"max_violations": 0}, ObservedOutcome({"exit_code": 0, "violation_count": 1})
    )
    assert outcome.status is VerificationStatus.FAILED


def test_lint_inconclusive_when_missing_evidence() -> None:
    outcome = evaluate_lint({}, ObservedOutcome({"exit_code": 0}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_type_check_passes_within_threshold() -> None:
    outcome = evaluate_type_check(
        {"max_errors": 0}, ObservedOutcome({"exit_code": 0, "error_count": 0})
    )
    assert outcome.status is VerificationStatus.PASSED


def test_type_check_fails_above_threshold() -> None:
    outcome = evaluate_type_check(
        {"max_errors": 0}, ObservedOutcome({"exit_code": 0, "error_count": 5})
    )
    assert outcome.status is VerificationStatus.FAILED


def test_lint_raises_on_negative_threshold() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_lint(
            {"max_violations": -1}, ObservedOutcome({"exit_code": 0, "violation_count": 0})
        )


# --- unit_test -------------------------------------------------------------------------


def test_unit_test_passes_when_all_pass() -> None:
    outcome = evaluate_unit_test(
        {}, ObservedOutcome({"exit_code": 0, "tests_total": 12, "tests_failed": 0})
    )
    assert outcome.status is VerificationStatus.PASSED


def test_unit_test_fails_when_any_failed() -> None:
    outcome = evaluate_unit_test(
        {}, ObservedOutcome({"exit_code": 1, "tests_total": 12, "tests_failed": 2})
    )
    assert outcome.status is VerificationStatus.FAILED


def test_unit_test_inconclusive_when_below_min_tests() -> None:
    outcome = evaluate_unit_test(
        {"min_tests": 10}, ObservedOutcome({"exit_code": 0, "tests_total": 3, "tests_failed": 0})
    )
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_unit_test_inconclusive_when_missing_evidence() -> None:
    outcome = evaluate_unit_test({}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_unit_test_raises_on_malformed_criteria() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_unit_test({"min_tests": -1}, ObservedOutcome({"exit_code": 0}))


# --- file_diff --------------------------------------------------------------------------


def test_file_diff_passes_on_matching_diff() -> None:
    outcome = evaluate_file_diff({"expected_diff": "+line"}, ObservedOutcome({"diff": "+line"}))
    assert outcome.status is VerificationStatus.PASSED


def test_file_diff_fails_on_different_diff() -> None:
    outcome = evaluate_file_diff({"expected_diff": "+line"}, ObservedOutcome({"diff": "+other"}))
    assert outcome.status is VerificationStatus.FAILED


def test_file_diff_passes_on_matching_file_set() -> None:
    outcome = evaluate_file_diff(
        {"expected_files_changed": ["a.py", "b.py"]},
        ObservedOutcome({"files_changed": ["b.py", "a.py"]}),
    )
    assert outcome.status is VerificationStatus.PASSED


def test_file_diff_fails_on_different_file_set() -> None:
    outcome = evaluate_file_diff(
        {"expected_files_changed": ["a.py"]}, ObservedOutcome({"files_changed": ["b.py"]})
    )
    assert outcome.status is VerificationStatus.FAILED


def test_file_diff_inconclusive_when_missing_evidence() -> None:
    outcome = evaluate_file_diff({"expected_diff": "+line"}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


def test_file_diff_raises_when_no_criteria_given() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        evaluate_file_diff({}, ObservedOutcome({"diff": "+line"}))


# --- human_reviewed -----------------------------------------------------------------------


def test_human_reviewed_requires_review_when_absent() -> None:
    outcome = evaluate_human_reviewed({}, ObservedOutcome({}))
    assert outcome.status is VerificationStatus.REQUIRES_HUMAN_REVIEW


def test_human_reviewed_passes_when_approved() -> None:
    outcome = evaluate_human_reviewed(
        {}, ObservedOutcome({"human_review_status": "approved", "human_reviewer": "alice"})
    )
    assert outcome.status is VerificationStatus.PASSED
    assert outcome.reviewer_type == "alice"


def test_human_reviewed_fails_when_rejected() -> None:
    outcome = evaluate_human_reviewed({}, ObservedOutcome({"human_review_status": "rejected"}))
    assert outcome.status is VerificationStatus.FAILED
    assert outcome.failure_reason


def test_human_reviewed_inconclusive_on_unrecognized_status() -> None:
    outcome = evaluate_human_reviewed({}, ObservedOutcome({"human_review_status": "maybe"}))
    assert outcome.status is VerificationStatus.INCONCLUSIVE


# --- determinism, per-evaluator --------------------------------------------------------------


def test_evaluators_are_deterministic_across_repeated_calls() -> None:
    criteria = {"expected": "hello"}
    observed = ObservedOutcome({"output": "hello"})
    first = evaluate_exact_match(criteria, observed)
    for _ in range(20):
        again = evaluate_exact_match(criteria, observed)
        assert again.status == first.status
        assert again.failure_reason == first.failure_reason


# --- safety: no unsafe arbitrary shell execution -----------------------------------------------


def test_malicious_looking_criteria_never_executes_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a criteria value shaped like a dangerous shell command must
    never be executed -- evaluators are pure functions over structured
    data, never `subprocess`/`os.system`/`eval`/`exec`."""
    import subprocess

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no evaluator should ever invoke subprocess")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    malicious = "; rm -rf / #"
    outcome = evaluate_exact_match({"expected": malicious}, ObservedOutcome({"output": malicious}))
    assert outcome.status is VerificationStatus.PASSED  # plain string comparison only

    outcome = evaluate_regex({"pattern": "rm -rf"}, ObservedOutcome({"output": malicious}))
    assert outcome.status is VerificationStatus.PASSED  # plain regex match only


def test_null_command_executor_always_refuses() -> None:
    executor = NullCommandExecutor()
    spec = CommandSpec(argv=("echo", "hi"))
    with pytest.raises(CommandExecutionNotConfiguredError):
        executor.run(spec)


def test_command_spec_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="argv"):
        CommandSpec(argv=())


def test_command_spec_has_no_shell_or_env_field() -> None:
    """Structural guarantee: `CommandSpec` cannot carry a raw shell string or
    environment overrides -- both would be safety holes for an injected
    executor."""
    field_names = {f for f in CommandSpec.__dataclass_fields__}
    assert "shell" not in field_names
    assert "env" not in field_names


# --- safety: reasoning-shaped evidence blocked ------------------------------------------------


def test_observed_outcome_rejects_chain_of_thought_key() -> None:
    with pytest.raises(UnsafeEvidenceError):
        ObservedOutcome({"output": "ok", "chain_of_thought": "secret reasoning"})


def test_observed_outcome_rejects_nested_reasoning_key() -> None:
    with pytest.raises(UnsafeEvidenceError):
        ObservedOutcome({"output": {"details": {"hidden_reasoning": "secret"}}})


def test_observed_outcome_accepts_benign_key_mentioning_reasoning() -> None:
    outcome = ObservedOutcome({"reasoning_step_count": 4})
    assert outcome.data == {"reasoning_step_count": 4}


def test_evaluator_evidence_value_is_a_real_verification_evidence_instance() -> None:
    """Every evaluator's evidence entries are already-validated
    `VerificationEvidence` objects (contract-level `reject_reasoning_shaped_keys`
    applies automatically), not bare dicts an evaluator could smuggle
    unsafe content through."""
    from app.contracts.verification import VerificationEvidence

    outcome = evaluate_exact_match({"expected": "x"}, ObservedOutcome({"output": "x"}))
    assert all(isinstance(item, VerificationEvidence) for item in outcome.evidence)
