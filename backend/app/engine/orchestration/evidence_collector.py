"""Provider-neutral, policy-driven collection of REAL objective evidence
from a step's actual persistent workspace, for evaluator types whose
`ObservedOutcome.data` contract (`app.engine.verification.evaluators`)
needs more than a CLI process's own free-text response -- `build`,
`unit_test`, and `file_diff`.

**Why this exists (Stage 8C.3 P1 fix).** A real local-CLI-agent step (any
provider -- this module never inspects which one) can genuinely
create/modify working files and pass its own real test suite, but until
now nothing ever ran a real, independent check against the resulting
workspace and fed the result back as evidence -- so every evaluator needing
more than `content` reported `INCONCLUSIVE` by design (see
`evaluators.py`'s own module docstring), and Stage 4E recovery endlessly
retried a step that had, in objective fact, already succeeded. This module
is the "else" branch of the required design: "if trustworthy structured
evidence already present: consume it; else if real workspace execution:
collect objective evidence" -- see `WorkspaceEvidenceCollector.collect`.

**What this never does:**

- Never executes a command derived from prompt text, a model's response,
  ConnectedAgent metadata, a webview, or a README -- the command is always
  chosen by the fixed policy below, from the evaluator's own
  `evaluator_type`/`criteria` plus what files objectively exist under
  `workspace_root`.
- Never runs an arbitrary `package.json` script (`npm test`, `npm run
  build`, ...) -- only Node's own built-in test runner / syntax checker, or
  Python's standard-library `unittest`/`py_compile`, invoked directly with
  bounded, deterministically-discovered file arguments
  (`command_executor.ALLOWED_EXECUTABLES`).
- Never invents `tests_total`/`tests_failed` when a real test command's
  output could not be reliably parsed -- the real `exit_code` is still
  reported; unparsed counts are simply omitted, which `evaluate_unit_test`
  already treats as `INCONCLUSIVE` (missing evidence), never a fabricated
  pass.
- Never overwrites an evidence key an executor's own `output_payload`
  already provided -- see `WorkspaceEvidenceCollector.collect`.
- Never mentions or branches on any specific provider (`claude`, `codex`,
  `gemini`, `antigravity`, `openrouter`, ...) -- this module only ever
  looks at `evaluator_type`/`criteria`/the workspace filesystem.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.orchestration.command_executor import SubprocessCommandExecutor
from app.engine.orchestration.workspace_snapshot import (
    EXCLUDED_DIR_NAMES,
    FileState,
    diff_snapshots,
    take_snapshot,
)
from app.engine.verification.evaluators import CommandExecutor, CommandSpec

_COMMAND_TIMEOUT_SECONDS = 60.0
_MAX_DISCOVERED_FILES = 50

_NODE_TEST_NAME_RE = re.compile(r"\.(?:test|spec)\.m?js$")
_PY_TEST_NAME_RE = re.compile(r"^(?:test_.*\.py|.*_test\.py)$")

_TAP_COUNT_RE = re.compile(r"^# (tests|pass|fail) (\d+)$", re.MULTILINE)
_UNITTEST_RAN_RE = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
_UNITTEST_OK_RE = re.compile(r"^OK\b", re.MULTILINE)
_UNITTEST_FAILURES_RE = re.compile(r"failures=(\d+)")
_UNITTEST_ERRORS_RE = re.compile(r"errors=(\d+)")


def _discover_files(root: Path, predicate: Callable[[Path], bool]) -> list[str]:
    """Deterministic (sorted), bounded, excluded-dir-aware file discovery --
    shared shape with `workspace_snapshot._iter_candidate_files`, kept
    separate since this one filters by a caller predicate rather than
    collecting everything."""
    matches: list[str] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIR_NAMES:
                    stack.append(entry)
            elif entry.is_file() and predicate(entry):
                matches.append(entry.relative_to(root).as_posix())
    matches.sort()
    return matches[:_MAX_DISCOVERED_FILES]


def _discover_node_test_files(root: Path) -> list[str]:
    return _discover_files(root, lambda p: _NODE_TEST_NAME_RE.search(p.name) is not None)


def _discover_python_test_files(root: Path) -> list[str]:
    return _discover_files(root, lambda p: _PY_TEST_NAME_RE.match(p.name) is not None)


def _discover_js_source_files(root: Path) -> list[str]:
    return _discover_files(
        root,
        lambda p: p.suffix in (".js", ".mjs") and _NODE_TEST_NAME_RE.search(p.name) is None,
    )


def _discover_python_source_files(root: Path) -> list[str]:
    return _discover_files(
        root, lambda p: p.suffix == ".py" and _PY_TEST_NAME_RE.match(p.name) is None
    )


def _parse_node_tap_counts(stdout: str) -> dict[str, int]:
    found = {key: int(value) for key, value in _TAP_COUNT_RE.findall(stdout)}
    if {"tests", "pass", "fail"} <= found.keys():
        return {"tests_total": found["tests"], "tests_failed": found["fail"]}
    return {}


def _run_node_tests(
    executor: CommandExecutor, workspace_root: str, files: list[str]
) -> dict[str, Any]:
    outcome = executor.run(
        CommandSpec(
            argv=("node", "--test", "--test-reporter=tap", *files),
            cwd=workspace_root,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
    )
    evidence: dict[str, Any] = {"exit_code": outcome.exit_code}
    if not outcome.timed_out:
        evidence.update(_parse_node_tap_counts(outcome.stdout))
    return evidence


def _parse_unittest_counts(output: str) -> dict[str, int]:
    ran_match = _UNITTEST_RAN_RE.search(output)
    if not ran_match:
        return {}
    total = int(ran_match.group(1))
    if _UNITTEST_OK_RE.search(output):
        return {"tests_total": total, "tests_failed": 0}
    failures_match = _UNITTEST_FAILURES_RE.search(output)
    errors_match = _UNITTEST_ERRORS_RE.search(output)
    if failures_match or errors_match:
        failed = int(failures_match.group(1) if failures_match else 0) + int(
            errors_match.group(1) if errors_match else 0
        )
        return {"tests_total": total, "tests_failed": failed}
    return {}


def _run_python_tests(executor: CommandExecutor, workspace_root: str) -> dict[str, Any]:
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"),
            cwd=workspace_root,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
    )
    evidence: dict[str, Any] = {"exit_code": outcome.exit_code}
    if not outcome.timed_out:
        evidence.update(_parse_unittest_counts(outcome.stdout + "\n" + outcome.stderr))
    return evidence


def _collect_test_evidence(executor: CommandExecutor, workspace_root: str) -> dict[str, Any]:
    """Deterministic runner selection: Node test files (if any) take
    priority over Python test files -- a project is never both at once in
    practice, and this order is fixed, not content-dependent."""
    root = Path(workspace_root)
    node_files = _discover_node_test_files(root)
    if node_files:
        return _run_node_tests(executor, workspace_root, node_files)
    if _discover_python_test_files(root):
        return _run_python_tests(executor, workspace_root)
    return {}


def _run_node_syntax_check(
    executor: CommandExecutor, workspace_root: str, files: list[str]
) -> int:
    for relative_path in files:
        outcome = executor.run(
            CommandSpec(
                argv=("node", "--check", relative_path),
                cwd=workspace_root,
                timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
            )
        )
        if outcome.exit_code != 0:
            return outcome.exit_code
    return 0


def _run_python_syntax_check(
    executor: CommandExecutor, workspace_root: str, files: list[str]
) -> int:
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-m", "py_compile", *files),
            cwd=workspace_root,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
    )
    return outcome.exit_code


def _collect_build_evidence(
    executor: CommandExecutor, workspace_root: str, *, also_run_tests: bool
) -> dict[str, Any]:
    """`require_clean_build` alone: a real syntax-level build check only
    (no compiler is assumed to exist for a static/interpreted project).
    `require_build_and_test` (the planner's own documented shorthand,
    `evaluators.evaluate_build`): the same build check, plus a real test
    run, combined into one exit code -- a real build failure always wins
    over a test result; otherwise the real test exit code is reported.
    Never fabricates a combined result neither real command produced."""
    root = Path(workspace_root)
    js_files = _discover_js_source_files(root)
    py_files = _discover_python_source_files(root)

    build_exit_code: int | None = None
    if js_files:
        build_exit_code = _run_node_syntax_check(executor, workspace_root, js_files)
    elif py_files:
        build_exit_code = _run_python_syntax_check(executor, workspace_root, py_files)

    if not also_run_tests:
        return {} if build_exit_code is None else {"exit_code": build_exit_code}

    test_evidence = _collect_test_evidence(executor, workspace_root)
    if build_exit_code is None and not test_evidence:
        return {}

    evidence = dict(test_evidence)
    build_failed = build_exit_code is not None and build_exit_code != 0
    evidence["exit_code"] = build_exit_code if build_failed else test_evidence.get("exit_code", 0)
    return evidence


class WorkspaceEvidenceCollector:
    """Rolls a bounded before/after workspace snapshot across successive
    `collect()` calls (one per verified step, in the order the caller
    verifies them) and, only for evaluator types whose evidence a real CLI
    response never carries, runs a real, policy-chosen, bounded command
    against the workspace. A fresh instance must be created per
    orchestration attempt (a full run, or one recovery cycle) so its
    rolling snapshot starts from that attempt's own initial workspace
    state -- never shared across unrelated orchestration requests.

    The initial snapshot is taken eagerly, in `__init__`, not lazily on the
    first `collect()` call: the caller (`service._make_verification_resolver`)
    always constructs this before `WorkflowEngine.execute_workflow` runs any
    step, so `__init__` sees the workspace exactly as it was before this
    attempt's first step ran. Taking it lazily instead would have missed
    that first step's own real changes if it happened to be the first
    `file_diff`-checked step -- `collect()` would then compare the
    already-changed workspace against itself and report an empty diff."""

    def __init__(self, workspace_root: str, *, executor: CommandExecutor | None = None) -> None:
        self._workspace_root = workspace_root
        self._executor: CommandExecutor = executor or SubprocessCommandExecutor()
        self._before: dict[str, FileState] = take_snapshot(workspace_root)

    def collect(self, expected: ExpectedOutcome, existing: dict[str, Any]) -> dict[str, Any]:
        """Returns evidence keys to ADD to `existing` -- a step's real
        `output_payload`, read-only here. Never overwrites a key `existing`
        already has: trustworthy structured evidence an executor already
        supplied always wins over anything this collector could add."""
        after = take_snapshot(self._workspace_root)
        files_changed, diff_text = diff_snapshots(self._before, after)
        self._before = after

        if expected.evaluator_type is BenchmarkEvaluatorType.FILE_DIFF:
            collected: dict[str, Any] = {"files_changed": files_changed, "diff": diff_text}
        elif expected.evaluator_type is BenchmarkEvaluatorType.UNIT_TEST:
            if {"exit_code", "tests_total", "tests_failed"} <= existing.keys():
                collected = {}
            else:
                collected = _collect_test_evidence(self._executor, self._workspace_root)
        elif expected.evaluator_type is BenchmarkEvaluatorType.BUILD:
            if "exit_code" in existing:
                collected = {}
            else:
                also_run_tests = bool(expected.criteria.get("require_build_and_test"))
                collected = _collect_build_evidence(
                    self._executor, self._workspace_root, also_run_tests=also_run_tests
                )
        else:
            collected = {}

        return {key: value for key, value in collected.items() if key not in existing}


__all__ = ["WorkspaceEvidenceCollector"]
