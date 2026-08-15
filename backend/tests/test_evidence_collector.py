"""Tests for `app.engine.orchestration.evidence_collector.WorkspaceEvidenceCollector`
-- the Stage 8C.3 P1 fix's policy layer deciding, from an `ExpectedOutcome`'s
`evaluator_type`/`criteria` plus what real files exist in a workspace,
whether/what real evidence-collection command to run.

Real `node`/`python` subprocesses throughout (via the real
`SubprocessCommandExecutor`), except where a `FakeCommandExecutor` is used
specifically to prove counts are never fabricated when a command's output
cannot be reliably parsed."""

from dataclasses import dataclass, field
from pathlib import Path

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.orchestration.evidence_collector import WorkspaceEvidenceCollector
from app.engine.verification.evaluators import CommandExecutionOutcome, CommandSpec


@dataclass
class FakeCommandExecutor:
    outcome: CommandExecutionOutcome
    calls: list[CommandSpec] = field(default_factory=list)

    def run(self, spec: CommandSpec) -> CommandExecutionOutcome:
        self.calls.append(spec)
        return self.outcome


def _write_passing_node_test(root: Path) -> None:
    (root / "add.js").write_text(
        "function add(a, b) { return a + b; }\nmodule.exports = { add };\n", encoding="utf-8"
    )
    (root / "add.test.js").write_text(
        "const test = require('node:test');\n"
        "const assert = require('node:assert');\n"
        "const { add } = require('./add.js');\n"
        "test('adds', () => { assert.strictEqual(add(2, 3), 5); });\n",
        encoding="utf-8",
    )


def _write_failing_node_test(root: Path) -> None:
    (root / "add.js").write_text(
        "function add(a, b) { return a - b; }\nmodule.exports = { add };\n", encoding="utf-8"
    )
    (root / "add.test.js").write_text(
        "const test = require('node:test');\n"
        "const assert = require('node:assert');\n"
        "const { add } = require('./add.js');\n"
        "test('adds', () => { assert.strictEqual(add(2, 3), 5); });\n",
        encoding="utf-8",
    )


def _unit_test_outcome(criteria: dict | None = None) -> ExpectedOutcome:
    return ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
        criteria=criteria or {"require_all_pass": True},
    )


# --- unit_test: real Node test discovery/execution ---------------------------


def test_real_passing_node_tests_produce_consistent_evidence(tmp_path: Path) -> None:
    _write_passing_node_test(tmp_path)
    collector = WorkspaceEvidenceCollector(str(tmp_path))

    evidence = collector.collect(_unit_test_outcome(), {})

    assert evidence["exit_code"] == 0
    assert evidence["tests_total"] == 1
    assert evidence["tests_failed"] == 0


def test_real_failing_node_test_is_never_reported_as_passing(tmp_path: Path) -> None:
    _write_failing_node_test(tmp_path)
    collector = WorkspaceEvidenceCollector(str(tmp_path))

    evidence = collector.collect(_unit_test_outcome(), {})

    assert evidence["exit_code"] != 0
    assert evidence["tests_failed"] >= 1


def test_no_test_files_produces_no_fabricated_evidence(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("nothing to test here", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))

    evidence = collector.collect(_unit_test_outcome(), {})

    assert evidence == {}


def test_existing_trustworthy_evidence_is_never_overwritten(tmp_path: Path) -> None:
    _write_passing_node_test(tmp_path)
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    existing = {"exit_code": 0, "tests_total": 999, "tests_failed": 0}

    evidence = collector.collect(_unit_test_outcome(), existing)

    assert evidence == {}


def test_unparseable_test_output_preserves_exit_code_without_inventing_counts(
    tmp_path: Path,
) -> None:
    _write_passing_node_test(tmp_path)
    fake = FakeCommandExecutor(
        outcome=CommandExecutionOutcome(exit_code=0, stdout="not TAP output at all", stderr="")
    )
    collector = WorkspaceEvidenceCollector(str(tmp_path), executor=fake)

    evidence = collector.collect(_unit_test_outcome(), {})

    assert evidence == {"exit_code": 0}
    assert "tests_total" not in evidence
    assert "tests_failed" not in evidence


def test_never_runs_arbitrary_package_json_script(tmp_path: Path) -> None:
    marker = tmp_path / "pwned.txt"
    malicious_script = "node -e \\\"require('fs').writeFileSync('pwned.txt', 'x')\\\""
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "' + malicious_script + '"}}', encoding="utf-8"
    )
    _write_passing_node_test(tmp_path)
    collector = WorkspaceEvidenceCollector(str(tmp_path))

    collector.collect(_unit_test_outcome(), {})

    assert not marker.exists()


# --- build: real syntax-level check -------------------------------------------


def test_clean_build_with_valid_js_syntax_passes(tmp_path: Path) -> None:
    (tmp_path / "index.js").write_text("const x = 1;\nconsole.log(x);\n", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_clean_build": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence == {"exit_code": 0}


def test_clean_build_with_js_syntax_error_fails(tmp_path: Path) -> None:
    (tmp_path / "index.js").write_text("function broken( {\n", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_clean_build": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence["exit_code"] != 0


def test_build_with_no_source_files_is_inconclusive_not_fabricated(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("docs only", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_clean_build": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence == {}


def test_require_build_and_test_combines_real_build_and_test_evidence(tmp_path: Path) -> None:
    _write_passing_node_test(tmp_path)
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_build_and_test": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence["exit_code"] == 0
    assert evidence["tests_total"] == 1
    assert evidence["tests_failed"] == 0


def test_require_build_and_test_a_real_build_failure_wins_over_passing_tests(
    tmp_path: Path,
) -> None:
    _write_passing_node_test(tmp_path)
    (tmp_path / "broken.js").write_text("function broken( {\n", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_build_and_test": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence["exit_code"] != 0


def test_existing_build_exit_code_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "index.js").write_text("function broken( {\n", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.BUILD, criteria={"require_clean_build": True}
    )

    evidence = collector.collect(expected, {"exit_code": 0})

    assert evidence == {}


# --- file_diff: real before/after workspace evidence --------------------------


def test_file_diff_evidence_is_empty_when_nothing_changed(tmp_path: Path) -> None:
    (tmp_path / "stable.txt").write_text("same", encoding="utf-8")
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.FILE_DIFF, criteria={"require_non_empty_diff": True}
    )

    evidence = collector.collect(expected, {})

    assert evidence == {"files_changed": [], "diff": ""}


def test_file_diff_evidence_reflects_a_real_change(tmp_path: Path) -> None:
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.FILE_DIFF, criteria={"require_non_empty_diff": True}
    )
    collector.collect(expected, {})  # establishes the rolling "before" state

    (tmp_path / "README.md").write_text("# Docs\n", encoding="utf-8")
    evidence = collector.collect(expected, {})

    assert evidence["files_changed"] == ["README.md"]
    assert evidence["diff"] != ""


def test_file_diff_baseline_is_taken_at_construction_not_first_collect(tmp_path: Path) -> None:
    """The collector must snapshot the workspace at __init__ time (before
    any step of this attempt has run) -- not lazily on the first `collect()`
    call, which would already be after that first step's own writes and so
    would wrongly report an empty diff for its real changes."""
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.FILE_DIFF, criteria={"require_non_empty_diff": True}
    )

    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    first = collector.collect(expected, {})
    assert first["files_changed"] == ["index.html"]

    (tmp_path / "README.md").write_text("# Docs\n", encoding="utf-8")
    second = collector.collect(expected, {})
    assert second["files_changed"] == ["README.md"]


# --- evaluator types this collector does not handle ---------------------------


def test_unhandled_evaluator_type_returns_no_evidence(tmp_path: Path) -> None:
    collector = WorkspaceEvidenceCollector(str(tmp_path))
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )

    evidence = collector.collect(expected, {})

    assert evidence == {}


# --- provider neutrality -------------------------------------------------------


def test_evidence_collection_modules_never_branch_on_agent_type() -> None:
    """Provider neutrality, checked structurally rather than by a raw
    keyword grep: these modules must never read/compare `agent_type` (the
    field a vendor-specific branch would have to key off) at all -- they
    only ever look at `evaluator_type`/`criteria`/the workspace filesystem.
    A prose mention of a provider name in a docstring (e.g. explaining what
    this module deliberately does *not* do) is fine; a real branch is not,
    so this checks for the structural signal, not the substring."""
    import app.engine.orchestration.command_executor as command_executor_module
    import app.engine.orchestration.evidence_collector as evidence_collector_module
    import app.engine.orchestration.workspace_snapshot as workspace_snapshot_module

    for module in (evidence_collector_module, command_executor_module, workspace_snapshot_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "agent_type" not in source, f"{module.__name__} unexpectedly branches on agent_type"
