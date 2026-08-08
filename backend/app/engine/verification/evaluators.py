"""Objective evaluator implementations for every `BenchmarkEvaluatorType`
value that currently exists (`app.contracts.enums`) -- inspected from the
real enum, not assumed: `exact_match`, `json_schema`, `regex`, `exit_code`,
`unit_test`, `build`, `lint`, `type_check`, `file_diff`, `human_reviewed`.

**Pure functions over already-collected evidence.** Every evaluator here
takes `(criteria, observed)` and returns an `EvaluatorOutcome` -- none of
them execute a process, open a socket, read an arbitrary file, or call an
external model. `ObservedOutcome` is Stage 4E's structured stand-in for
"whatever the Workflow Engine (Stage 2/3) already captured while actually
running the step" (`app.contracts.adapter.AgentExecutionResult` and
friends, upstream of this module) -- Verifier = "did it work?", checking
evidence that already exists, never Executor = "make it happen." This is
why there is no "run pytest" code anywhere in this file even though
`unit_test`/`build`/`lint`/`type_check` are evaluator *names*: their
observable evidence (exit code, test/violation/error counts) is supplied
by the caller, already collected.

**Safe execution boundary.** `CommandSpec`/`CommandExecutor` below is the
narrow, structured seam a future evidence-collection component would use
instead of ever building `subprocess.run(text, shell=True)` from
`ExpectedOutcome`/`criteria` text: `CommandSpec.argv` is an explicit
`tuple[str, ...]` (never a single shell string, so shell metacharacters in
any entry are inert), it has no `env` field (no evaluator input can ask an
executor to dump or override process environment/credentials), and the
only implementation shipped here, `NullCommandExecutor`, unconditionally
refuses. No evaluator in this module calls a `CommandExecutor` -- it exists
purely as documented, tested infrastructure for a later stage.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.contracts.evidence_safety import reject_reasoning_shaped_keys
from app.contracts.verification import VerificationEvidence, VerificationStatus
from app.engine.verification.errors import (
    CommandExecutionNotConfiguredError,
    MalformedExpectedOutcomeError,
    UnsafeEvidenceError,
)


@dataclass(frozen=True)
class ObservedOutcome:
    """Structured, already-collected observable evidence for one executed
    step's output, evaluated against one `ExpectedOutcome`. `data` keys are
    documented per evaluator below (e.g. `"output"`, `"exit_code"`,
    `"tests_total"`, `"diff"`, `"human_review_status"`); an evaluator never
    fabricates a missing key, it reports `INCONCLUSIVE`.

    Checked at construction for reserved reasoning-shaped keys (same
    vocabulary as `VerificationEvidence.value` and
    `app.contracts.explainability`) -- observed evidence may describe only
    Keystone's own measurable outputs, never a model's internal reasoning.
    """

    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            reject_reasoning_shaped_keys(self.data)
        except ValueError as exc:
            raise UnsafeEvidenceError(str(exc)) from exc


@dataclass(frozen=True)
class EvaluatorOutcome:
    """One evaluator's verdict, before `verifier.py` wraps it into a full
    `VerificationResult` (adding identity/timestamp fields)."""

    status: VerificationStatus
    evidence: list[VerificationEvidence] = field(default_factory=list)
    failure_reason: str | None = None
    confidence: float | None = None
    reviewer_type: str | None = None


EvaluatorFn = Callable[[dict[str, Any], ObservedOutcome], EvaluatorOutcome]


# --- Safe, narrow command-execution boundary (never invoked by an evaluator
# in this module -- see module docstring) -------------------------------------


@dataclass(frozen=True)
class CommandSpec:
    """A structured command -- argv-style only, never a shell string. No
    `shell` field exists by design (argv execution never invokes a shell
    interpreter, so shell metacharacters inside an `argv` entry are inert),
    and no `env` field exists either (an injected `CommandExecutor` must
    never receive instructions to dump or override process
    environment/credentials from evaluator input)."""

    argv: tuple[str, ...]
    cwd: str | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("argv must not be empty")
        if any(not isinstance(part, str) for part in self.argv):
            raise ValueError("argv entries must all be strings")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class CommandExecutionOutcome:
    """The result of running one `CommandSpec` -- itself a candidate source
    of `ObservedOutcome.data` for a caller that chooses to populate evidence
    this way, never consumed directly by any evaluator in this module."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class CommandExecutor(Protocol):
    """The narrow, injected execution boundary a caller may supply to
    collect real command evidence. No default implementation in Stage 4E
    touches the OS, a shell, or a filesystem beyond `CommandSpec.cwd` -- see
    `NullCommandExecutor`. A real implementation is entirely the injecting
    caller's own responsibility to sandbox."""

    def run(self, spec: CommandSpec) -> CommandExecutionOutcome: ...


class NullCommandExecutor:
    """The default `CommandExecutor`: always refuses. Guarantees that unless
    a caller explicitly injects a real executor, nothing in Stage 4E can
    ever cause a process to run."""

    def run(self, spec: CommandSpec) -> CommandExecutionOutcome:
        raise CommandExecutionNotConfiguredError(spec)


# --- Shared helpers -----------------------------------------------------------


def _evidence(
    kind: str, description: str, value: Any = None, source: str | None = None
) -> VerificationEvidence:
    return VerificationEvidence(kind=kind, description=description, value=value, source=source)


def _int_field(data: dict[str, Any], key: str) -> tuple[int | None, bool]:
    """Returns `(value, malformed)`. `value` is `None` if `key` is absent.
    `malformed=True` means `key` is present but not a plain `int` (`bool`
    excluded, since `bool` is an `int` subclass in Python)."""
    if key not in data:
        return None, False
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        return None, True
    return value, False


# --- exact_match ----------------------------------------------------------------


def evaluate_exact_match(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"expected": str}`. observed.data: `{"output": str}`."""
    if "expected" not in criteria or not isinstance(criteria["expected"], str):
        raise MalformedExpectedOutcomeError(
            "exact_match criteria requires a string 'expected' value"
        )
    expected = criteria["expected"]

    if "output" not in observed.data:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("exact_match", "no observed output was provided")],
        )
    output = observed.data["output"]
    if not isinstance(output, str):
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("exact_match", "observed output was not a string")],
        )

    matched = output == expected
    evidence = [
        _evidence(
            "exact_match",
            "compared observed output to the expected value",
            value={"matched": matched},
        )
    ]
    if matched:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason="observed output did not exactly match the expected value",
    )


# --- json_schema (deliberately narrow, dependency-free subset) ------------------

_JSON_SCHEMA_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _validate_json_schema_subset(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """A deliberately narrow, dependency-free subset of JSON Schema
    supporting `type`, `required`, `properties`, `items`, `enum` --
    sufficient for objective, deterministic structural verification. Not a
    full JSON Schema implementation and never claims to be."""
    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type is not None:
        expected = _JSON_SCHEMA_TYPE_MAP.get(schema_type)
        if expected is None:
            return [f"{path}: unsupported schema type '{schema_type}'"]
        if schema_type in ("integer", "number") and isinstance(value, bool):
            return [f"{path}: expected type '{schema_type}', got 'boolean'"]
        if not isinstance(value, expected):
            return [f"{path}: expected type '{schema_type}', got '{type(value).__name__}'"]

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        errors.append(f"{path}: value {value!r} is not one of the allowed enum values")

    if schema_type == "object" and isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")
        for key, subschema in (schema.get("properties") or {}).items():
            if key in value and isinstance(subschema, dict):
                errors.extend(_validate_json_schema_subset(value[key], subschema, f"{path}.{key}"))

    if schema_type == "array" and isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_json_schema_subset(item, items_schema, f"{path}[{index}]"))

    return errors


def evaluate_json_schema(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"schema": dict}`. observed.data: `{"output": <json-compatible value>}`."""
    schema = criteria.get("schema")
    if not isinstance(schema, dict):
        raise MalformedExpectedOutcomeError("json_schema criteria requires a 'schema' object")

    if "output" not in observed.data:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("json_schema", "no observed output was provided")],
        )

    errors = _validate_json_schema_subset(observed.data["output"], schema)
    evidence = [
        _evidence(
            "json_schema",
            "validated observed output against the schema",
            value={"errors": errors},
        )
    ]
    if errors:
        return EvaluatorOutcome(
            status=VerificationStatus.FAILED, evidence=evidence, failure_reason="; ".join(errors)
        )
    return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)


# --- regex ------------------------------------------------------------------------


def evaluate_regex(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"pattern": str}`. observed.data: `{"output": str}`."""
    pattern = criteria.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise MalformedExpectedOutcomeError("regex criteria requires a non-empty string 'pattern'")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise MalformedExpectedOutcomeError(
            f"regex criteria 'pattern' is not a valid regex: {exc}"
        ) from exc

    if "output" not in observed.data:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("regex", "no observed output was provided")],
        )
    output = observed.data["output"]
    if not isinstance(output, str):
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("regex", "observed output was not a string")],
        )

    matched = compiled.search(output) is not None
    evidence = [
        _evidence(
            "regex", "matched observed output against the pattern", value={"matched": matched}
        )
    ]
    if matched:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason="observed output did not match the required pattern",
    )


# --- exit_code / build (exit-code-based) -----------------------------------------


def _evaluate_exit_code_like(
    criteria: dict[str, Any], observed: ObservedOutcome, *, kind: str
) -> EvaluatorOutcome:
    expected = criteria.get("expected_exit_code", 0)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise MalformedExpectedOutcomeError(
            f"{kind} criteria 'expected_exit_code' must be an integer"
        )

    value, malformed = _int_field(observed.data, "exit_code")
    if malformed:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence(kind, "observed exit_code was not an integer")],
        )
    if value is None:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence(kind, "no observed exit_code was provided")],
        )

    evidence = [
        _evidence(
            kind,
            "compared observed exit code to expected",
            value={"observed": value, "expected": expected},
        )
    ]
    if value == expected:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason=f"{kind} exit code {value} did not match expected {expected}",
    )


def evaluate_exit_code(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"expected_exit_code": int = 0}`. observed.data: `{"exit_code": int}`."""
    return _evaluate_exit_code_like(criteria, observed, kind="exit_code")


def evaluate_build(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"expected_exit_code": int = 0}`. observed.data: `{"exit_code": int}`."""
    return _evaluate_exit_code_like(criteria, observed, kind="build")


# --- lint / type_check (threshold-based) -----------------------------------------


def _evaluate_threshold_like(
    criteria: dict[str, Any],
    observed: ObservedOutcome,
    *,
    kind: str,
    count_key: str,
    threshold_key: str,
) -> EvaluatorOutcome:
    threshold = criteria.get(threshold_key, 0)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 0:
        raise MalformedExpectedOutcomeError(
            f"{kind} criteria '{threshold_key}' must be a non-negative integer"
        )

    exit_value, exit_malformed = _int_field(observed.data, "exit_code")
    count_value, count_malformed = _int_field(observed.data, count_key)
    if exit_malformed or count_malformed:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence(kind, f"observed exit_code/{count_key} was not an integer")],
        )
    if exit_value is None or count_value is None:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence(kind, f"no observed exit_code/{count_key} was provided")],
        )

    evidence = [
        _evidence(
            kind,
            f"compared observed {count_key} to threshold",
            value={
                "observed_exit_code": exit_value,
                count_key: count_value,
                threshold_key: threshold,
            },
        )
    ]
    if exit_value == 0 and count_value <= threshold:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason=(
            f"{kind}: exit_code={exit_value}, {count_key}={count_value} "
            f"exceeded threshold {threshold}"
        ),
    )


def evaluate_lint(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"max_violations": int = 0}`. observed.data:
    `{"exit_code": int, "violation_count": int}`."""
    return _evaluate_threshold_like(
        criteria, observed, kind="lint", count_key="violation_count", threshold_key="max_violations"
    )


def evaluate_type_check(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"max_errors": int = 0}`. observed.data:
    `{"exit_code": int, "error_count": int}`."""
    return _evaluate_threshold_like(
        criteria, observed, kind="type_check", count_key="error_count", threshold_key="max_errors"
    )


# --- unit_test ----------------------------------------------------------------------


def evaluate_unit_test(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"min_tests": int = 1}`. observed.data:
    `{"exit_code": int, "tests_total": int, "tests_failed": int}`."""
    min_tests = criteria.get("min_tests", 1)
    if not isinstance(min_tests, int) or isinstance(min_tests, bool) or min_tests < 0:
        raise MalformedExpectedOutcomeError(
            "unit_test criteria 'min_tests' must be a non-negative integer"
        )

    exit_value, exit_malformed = _int_field(observed.data, "exit_code")
    total_value, total_malformed = _int_field(observed.data, "tests_total")
    failed_value, failed_malformed = _int_field(observed.data, "tests_failed")
    if exit_malformed or total_malformed or failed_malformed:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[
                _evidence(
                    "unit_test",
                    "observed exit_code/tests_total/tests_failed was not well-formed "
                    "(must be integers)",
                )
            ],
        )
    if exit_value is None or total_value is None or failed_value is None:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[
                _evidence(
                    "unit_test", "no observed exit_code/tests_total/tests_failed was provided"
                )
            ],
        )

    evidence = [
        _evidence(
            "unit_test",
            "compared observed test results to requirements",
            value={
                "exit_code": exit_value,
                "tests_total": total_value,
                "tests_failed": failed_value,
                "min_tests": min_tests,
            },
        )
    ]
    if total_value < min_tests:
        return EvaluatorOutcome(status=VerificationStatus.INCONCLUSIVE, evidence=evidence)
    if exit_value == 0 and failed_value == 0:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason=f"unit tests reported {failed_value} failure(s) (exit_code={exit_value})",
    )


# --- file_diff ------------------------------------------------------------------------


def evaluate_file_diff(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: either `{"expected_diff": str}` or
    `{"expected_files_changed": list[str]}` (checked in that priority order
    when both are present). observed.data: `{"diff": str}` or
    `{"files_changed": list[str]}` respectively."""
    has_diff = "expected_diff" in criteria
    has_files = "expected_files_changed" in criteria
    if not has_diff and not has_files:
        raise MalformedExpectedOutcomeError(
            "file_diff criteria requires either 'expected_diff' (str) or "
            "'expected_files_changed' (list[str])"
        )

    if has_diff:
        expected_diff = criteria["expected_diff"]
        if not isinstance(expected_diff, str):
            raise MalformedExpectedOutcomeError(
                "file_diff criteria 'expected_diff' must be a string"
            )
        if "diff" not in observed.data:
            return EvaluatorOutcome(
                status=VerificationStatus.INCONCLUSIVE,
                evidence=[_evidence("file_diff", "no observed diff was provided")],
            )
        observed_diff = observed.data["diff"]
        if not isinstance(observed_diff, str):
            return EvaluatorOutcome(
                status=VerificationStatus.INCONCLUSIVE,
                evidence=[_evidence("file_diff", "observed diff was not a string")],
            )
        matched = observed_diff == expected_diff
        evidence = [
            _evidence(
                "file_diff", "compared observed diff to expected diff", value={"matched": matched}
            )
        ]
        if matched:
            return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
        return EvaluatorOutcome(
            status=VerificationStatus.FAILED,
            evidence=evidence,
            failure_reason="observed diff did not match the expected diff",
        )

    expected_files = criteria["expected_files_changed"]
    if not isinstance(expected_files, list) or not all(isinstance(f, str) for f in expected_files):
        raise MalformedExpectedOutcomeError(
            "file_diff criteria 'expected_files_changed' must be a list of strings"
        )
    if "files_changed" not in observed.data:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("file_diff", "no observed files_changed was provided")],
        )
    observed_files = observed.data["files_changed"]
    if not isinstance(observed_files, list) or not all(isinstance(f, str) for f in observed_files):
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[_evidence("file_diff", "observed files_changed was not a list of strings")],
        )
    matched = set(observed_files) == set(expected_files)
    evidence = [
        _evidence(
            "file_diff",
            "compared observed changed files to expected set",
            value={
                "matched": matched,
                "observed_files": sorted(observed_files),
                "expected_files": sorted(expected_files),
            },
        )
    ]
    if matched:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason="observed changed files did not match the expected set",
    )


# --- human_reviewed ------------------------------------------------------------------


def evaluate_human_reviewed(
    criteria: dict[str, Any], observed: ObservedOutcome
) -> EvaluatorOutcome:
    """criteria: none required. observed.data:
    `{"human_review_status": "approved"|"rejected", "human_reviewer": str}`
    -- absence of `human_review_status` means review has not happened yet,
    which is `REQUIRES_HUMAN_REVIEW`, never a silent pass or fail."""
    del criteria  # unused: human_reviewed takes no criteria; kept for a stable EvaluatorFn shape
    status_value = observed.data.get("human_review_status")
    reviewer = observed.data.get("human_reviewer")

    if status_value is None:
        return EvaluatorOutcome(
            status=VerificationStatus.REQUIRES_HUMAN_REVIEW,
            evidence=[_evidence("human_reviewed", "no human review has been recorded yet")],
        )
    if not isinstance(status_value, str):
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[
                _evidence("human_reviewed", "observed human_review_status was not a string")
            ],
        )

    normalized = status_value.strip().lower()
    reviewer_type = reviewer if isinstance(reviewer, str) and reviewer.strip() else None

    if normalized == "approved":
        return EvaluatorOutcome(
            status=VerificationStatus.PASSED,
            evidence=[
                _evidence(
                    "human_reviewed",
                    "a human reviewer approved the output",
                    value={"status": normalized},
                )
            ],
            reviewer_type=reviewer_type,
        )
    if normalized == "rejected":
        return EvaluatorOutcome(
            status=VerificationStatus.FAILED,
            evidence=[
                _evidence(
                    "human_reviewed",
                    "a human reviewer rejected the output",
                    value={"status": normalized},
                )
            ],
            failure_reason="a human reviewer rejected the output",
            reviewer_type=reviewer_type,
        )
    return EvaluatorOutcome(
        status=VerificationStatus.INCONCLUSIVE,
        evidence=[
            _evidence(
                "human_reviewed",
                "human_review_status was not a recognized value",
                value={"status": status_value},
            )
        ],
    )


__all__ = [
    "CommandExecutionOutcome",
    "CommandExecutor",
    "CommandSpec",
    "EvaluatorFn",
    "EvaluatorOutcome",
    "NullCommandExecutor",
    "ObservedOutcome",
    "evaluate_build",
    "evaluate_exact_match",
    "evaluate_exit_code",
    "evaluate_file_diff",
    "evaluate_human_reviewed",
    "evaluate_json_schema",
    "evaluate_lint",
    "evaluate_regex",
    "evaluate_type_check",
    "evaluate_unit_test",
]
