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

# The complete, deliberately narrow set of JSON Schema keywords this
# evaluator understands. Any other keyword (`minLength`, `pattern`,
# `minimum`, `maximum`, `oneOf`, `anyOf`, `allOf`, `additionalProperties`,
# etc.) is a configuration error, never something silently skipped --
# skipping an unsupported keyword would let a value that should have failed
# under full JSON Schema semantics incorrectly PASS here.
_SUPPORTED_JSON_SCHEMA_KEYWORDS = frozenset(
    {"type", "enum", "required", "properties", "items", "$schema", "description", "title"}
)


def _validate_json_schema_keywords(schema: Any, path: str = "$") -> None:
    """Recursively reject any schema (at any nesting level, including inside
    `properties`/`items`) that uses a keyword outside
    `_SUPPORTED_JSON_SCHEMA_KEYWORDS`. Raises `MalformedExpectedOutcomeError`
    -- a typed configuration error -- rather than returning `INCONCLUSIVE`,
    since an unsupported keyword means the check *cannot* be performed
    correctly at all, not merely that evidence is missing."""
    if not isinstance(schema, dict):
        raise MalformedExpectedOutcomeError(
            f"json_schema criteria schema at {path} must be an object"
        )
    unsupported = sorted(set(schema) - _SUPPORTED_JSON_SCHEMA_KEYWORDS)
    if unsupported:
        raise MalformedExpectedOutcomeError(
            f"json_schema criteria schema at {path} uses unsupported keyword(s): "
            f"{', '.join(unsupported)}"
        )
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise MalformedExpectedOutcomeError(
                f"json_schema criteria 'properties' at {path} must be an object"
            )
        for key, subschema in properties.items():
            _validate_json_schema_keywords(subschema, f"{path}.{key}")
    items = schema.get("items")
    if items is not None:
        _validate_json_schema_keywords(items, f"{path}[]")


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
    """criteria: `{"schema": dict}`, restricted to
    `_SUPPORTED_JSON_SCHEMA_KEYWORDS`. observed.data:
    `{"output": <json-compatible value>}`."""
    schema = criteria.get("schema")
    if not isinstance(schema, dict):
        raise MalformedExpectedOutcomeError("json_schema criteria requires a 'schema' object")
    _validate_json_schema_keywords(schema)

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

# Bounded defensive limits, not a safety proof: `MAX_REGEX_PATTERN_LENGTH`
# and `MAX_REGEX_INPUT_LENGTH` cap the worst-case size of what `re.compile`/
# `.search` is ever asked to process here, and `_looks_catastrophically_nested`
# rejects the single best-known catastrophic-backtracking pattern shape by
# inspecting the pattern *text* (never by executing it). None of this is a
# general ReDoS analyzer or a substitute for a real safe-regex engine -- it
# will not catch every dangerous pattern, and it may reject some unusual but
# harmless ones. Documented here so that limitation is never mistaken for a
# stronger guarantee than it is.
MAX_REGEX_PATTERN_LENGTH = 500
MAX_REGEX_INPUT_LENGTH = 100_000

# Matches a group containing a quantified atom (`+`/`*`) that is itself
# immediately followed by an outer quantifier -- the shape of `(a+)+`,
# `(a*)+`, `(.+)+`, `(.*)+`, and similar classic catastrophic-backtracking
# patterns. Deliberately simple (no nested-group parsing): a single-level,
# text-based heuristic, conservative by design (see module note above).
_CATASTROPHIC_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*][^()]*\)[+*]")


def _looks_catastrophically_nested(pattern: str) -> bool:
    return _CATASTROPHIC_NESTED_QUANTIFIER_RE.search(pattern) is not None


def evaluate_regex(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"pattern": str}`. observed.data: `{"output": str}`.

    Defensively bounded (see the `MAX_REGEX_*` constants and
    `_looks_catastrophically_nested` above): an oversized or
    catastrophically-nested-looking pattern is rejected as malformed
    criteria *before* `re.compile` is ever called, and an oversized observed
    output is reported `INCONCLUSIVE` -- never handed to `.search` at all.
    """
    pattern = criteria.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise MalformedExpectedOutcomeError("regex criteria requires a non-empty string 'pattern'")
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise MalformedExpectedOutcomeError(
            f"regex criteria 'pattern' exceeds the maximum allowed length of "
            f"{MAX_REGEX_PATTERN_LENGTH} characters"
        )
    if _looks_catastrophically_nested(pattern):
        raise MalformedExpectedOutcomeError(
            "regex criteria 'pattern' looks like a catastrophic-backtracking-prone "
            "nested quantifier (e.g. '(a+)+') and was rejected defensively"
        )
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
    if len(output) > MAX_REGEX_INPUT_LENGTH:
        return EvaluatorOutcome(
            status=VerificationStatus.INCONCLUSIVE,
            evidence=[
                _evidence(
                    "regex",
                    "observed output exceeds the maximum safely-checkable length of "
                    f"{MAX_REGEX_INPUT_LENGTH} characters",
                )
            ],
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


# Stage 4D planner shorthand keys (`app.engine.planning.templates`):
# `require_clean_build` and `require_build_and_test` are both boolean flags
# that mean "the build's exit code must be 0" -- `require_build_and_test`
# additionally implies the invoked build step also ran tests as part of the
# same command (e.g. `npm run build && npm test`), so its single exit code
# already reflects both outcomes. This evaluator never fabricates separate
# test evidence it wasn't given; a plan wanting a distinct pass/fail test
# count uses a sibling UNIT_TEST-evaluated task instead (as most planner
# templates already do). When `True`, either key takes precedence over any
# separately supplied `expected_exit_code`, since "clean build" is
# unambiguous: exit code 0.
_BUILD_BOOLEAN_CRITERIA_KEYS = ("require_clean_build", "require_build_and_test")


def evaluate_build(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: `{"expected_exit_code": int = 0}`, or either of the Stage 4D
    planner's boolean shorthands `{"require_clean_build": bool}` /
    `{"require_build_and_test": bool}` (see `_BUILD_BOOLEAN_CRITERIA_KEYS`).
    observed.data: `{"exit_code": int}`."""
    forced_clean = False
    for key in _BUILD_BOOLEAN_CRITERIA_KEYS:
        if key not in criteria:
            continue
        value = criteria[key]
        if not isinstance(value, bool):
            raise MalformedExpectedOutcomeError(f"build criteria '{key}' must be a boolean")
        forced_clean = forced_clean or value

    resolved_criteria = {**criteria, "expected_exit_code": 0} if forced_clean else criteria
    return _evaluate_exit_code_like(resolved_criteria, observed, kind="build")


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
    """criteria: `{"min_tests": int = 1}`, and/or the Stage 4D planner's
    boolean shorthand `{"require_all_pass": bool}`. observed.data:
    `{"exit_code": int, "tests_total": int, "tests_failed": int}`.

    `require_all_pass=True` means "exit_code=0 AND tests_failed=0 AND
    positive evidence of test execution" -- explicitly enforced here by
    raising `min_tests` to at least `1` (never lower than any caller-given
    `min_tests`), so `tests_total=0` can never satisfy it even if `min_tests`
    was otherwise left unset or set to `0`. This is a real behavior
    difference, not just a validated-and-dropped flag: without it, a
    `min_tests=0`+`require_all_pass=True` combination would let zero
    executed tests count as "all passed".
    """
    min_tests = criteria.get("min_tests", 1)
    if not isinstance(min_tests, int) or isinstance(min_tests, bool) or min_tests < 0:
        raise MalformedExpectedOutcomeError(
            "unit_test criteria 'min_tests' must be a non-negative integer"
        )

    require_all_pass = criteria.get("require_all_pass")
    if require_all_pass is not None and not isinstance(require_all_pass, bool):
        raise MalformedExpectedOutcomeError(
            "unit_test criteria 'require_all_pass' must be a boolean"
        )
    if require_all_pass:
        min_tests = max(min_tests, 1)

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


def _evaluate_file_diff_expected_diff(
    criteria: dict[str, Any], observed: ObservedOutcome
) -> EvaluatorOutcome:
    expected_diff = criteria["expected_diff"]
    if not isinstance(expected_diff, str):
        raise MalformedExpectedOutcomeError("file_diff criteria 'expected_diff' must be a string")
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


def _evaluate_file_diff_expected_files_changed(
    criteria: dict[str, Any], observed: ObservedOutcome
) -> EvaluatorOutcome:
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


def _evaluate_file_diff_non_empty_diff(observed: ObservedOutcome) -> EvaluatorOutcome:
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
    non_empty = len(observed_diff) > 0
    evidence = [
        _evidence(
            "file_diff",
            "checked whether the observed diff is non-empty",
            value={"non_empty": non_empty},
        )
    ]
    if non_empty:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason="observed diff was empty; a non-empty diff was required",
    )


def _evaluate_file_diff_non_empty_files_changed(observed: ObservedOutcome) -> EvaluatorOutcome:
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
    non_empty = len(observed_files) > 0
    evidence = [
        _evidence(
            "file_diff",
            "checked whether observed files_changed is non-empty",
            value={"non_empty": non_empty, "count": len(observed_files)},
        )
    ]
    if non_empty:
        return EvaluatorOutcome(status=VerificationStatus.PASSED, evidence=evidence)
    return EvaluatorOutcome(
        status=VerificationStatus.FAILED,
        evidence=evidence,
        failure_reason="observed files_changed was empty; a non-empty list was required",
    )


def evaluate_file_diff(criteria: dict[str, Any], observed: ObservedOutcome) -> EvaluatorOutcome:
    """criteria: exactly one of --

    - `{"expected_diff": str}` -- observed `"diff"` must match exactly.
    - `{"expected_files_changed": list[str]}` -- observed `"files_changed"`
      must match as a set.
    - `{"require_non_empty_diff": bool}` -- the Stage 4D planner's shorthand;
      observed `"diff"` must be present and non-empty.
    - `{"require_non_empty_files_changed": bool}` -- observed
      `"files_changed"` must be present and non-empty.

    Checked in that priority order when more than one key is present.
    Missing/empty observed evidence never PASSes for the `require_non_empty_*`
    keys: missing is `INCONCLUSIVE` (no evidence to judge), a present-but-
    empty diff/list is `FAILED` (well-formed evidence that fails the check).
    """
    for boolean_key in ("require_non_empty_diff", "require_non_empty_files_changed"):
        if boolean_key in criteria and not isinstance(criteria[boolean_key], bool):
            raise MalformedExpectedOutcomeError(
                f"file_diff criteria '{boolean_key}' must be a boolean"
            )

    if "expected_diff" in criteria:
        return _evaluate_file_diff_expected_diff(criteria, observed)
    if "expected_files_changed" in criteria:
        return _evaluate_file_diff_expected_files_changed(criteria, observed)
    if criteria.get("require_non_empty_diff") is True:
        return _evaluate_file_diff_non_empty_diff(observed)
    if criteria.get("require_non_empty_files_changed") is True:
        return _evaluate_file_diff_non_empty_files_changed(observed)

    raise MalformedExpectedOutcomeError(
        "file_diff criteria requires one of 'expected_diff', 'expected_files_changed', "
        "'require_non_empty_diff', or 'require_non_empty_files_changed'"
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
    "MAX_REGEX_INPUT_LENGTH",
    "MAX_REGEX_PATTERN_LENGTH",
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
