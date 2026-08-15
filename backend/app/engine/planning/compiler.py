"""Task Graph Compiler V2 (Agent-Independent DAG Decomposition).

Decomposes user goals into a typed executable DAG (WorkflowPlan with enriched TaskSpecs)
using semantic concern extraction, action verb analysis, workspace context, and dynamic
dependency inference across single and multi-concern composite domains.

Does NOT assign agent_type or take connected agents as required input.
WHO does the work is decided later by AgentOrganizationCompiler and Router.
"""

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, TaskSpec, _detect_cycle


class TargetFileOwnership(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ComplexityLevel(StrEnum):
    TRIVIAL = "TRIVIAL"
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class CompiledTaskNode(BaseModel):
    """Executable node in a Task Graph Compiler DAG."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: str
    title: str
    objective: str
    dependencies: list[str] = Field(default_factory=list)
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    preferred_capabilities: list[AgentCapability] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    target_files_ownership: TargetFileOwnership = TargetFileOwnership.UNKNOWN
    verification_requirements: dict[str, Any] = Field(default_factory=dict)
    parallel_safe: bool = False
    estimated_complexity: ComplexityLevel = ComplexityLevel.SIMPLE
    skill_id: str | None = None
    skill_version: str | None = None
    skill_name: str | None = None
    skill_guidance: str | None = None

    def to_task_spec(self) -> TaskSpec:
        """Convert compiler node to standard contract TaskSpec."""
        input_payload = {
            "title": self.title,
            "objective": self.objective,
            "target_files": self.target_files,
            "target_files_ownership": self.target_files_ownership.value,
            "parallel_safe": self.parallel_safe,
            "estimated_complexity": self.estimated_complexity.value,
            "preferred_capabilities": [c.value for c in self.preferred_capabilities],
            "verification_requirements": self.verification_requirements,
        }
        if self.skill_id:
            input_payload["skill_id"] = self.skill_id
            input_payload["skill_version"] = self.skill_version
            input_payload["skill_name"] = self.skill_name
            input_payload["skill_guidance"] = self.skill_guidance
        outcome = None
        if self.verification_requirements:
            eval_type = self.verification_requirements.get(
                "evaluator_type", BenchmarkEvaluatorType.UNIT_TEST
            )
            outcome = ExpectedOutcome(
                evaluator_type=eval_type,
                criteria=self.verification_requirements.get("criteria", {}),
                description=self.verification_requirements.get("description", self.objective),
            )

        return TaskSpec(
            key=self.task_id,
            name=self.title,
            task_type=self.task_type,
            required_capabilities=self.required_capabilities,
            depends_on=self.dependencies,
            input_payload=input_payload,
            expected_outcome=outcome,
        )


class TaskGraphCompilerV2:
    """Agent-independent deterministic Task Graph Compiler.

    Analyzes goal structure, extracts concerns, workspace context, and dependencies
    dynamically without rigid keyword-to-template dispatching.
    """

    MAX_TASKS = 10
    MAX_DEPTH = 5

    def compile(
        self,
        goal: str,
        workspace_context: dict[str, Any] | None = None,
        project_metadata: dict[str, Any] | None = None,
        user_constraints: dict[str, Any] | None = None,
    ) -> list[CompiledTaskNode]:
        """Compile a user goal and context into a typed executable DAG task graph."""
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")

        goal_clean = goal.strip()
        analysis = self._analyze_goal_structure(
            goal_clean, workspace_context, project_metadata, user_constraints
        )

        nodes = self._extract_concerns_and_build_dag(analysis)

        # Enforce parallel safety derivation from file ownership & overlaps
        self._derive_parallel_safety(nodes)

        # Validate bounds (task count limit, duplicate IDs, cycles, MAX_DEPTH)
        self._validate_and_bound_graph(nodes)

        return nodes

    def _analyze_goal_structure(
        self,
        goal: str,
        workspace_context: dict[str, Any] | None,
        project_metadata: dict[str, Any] | None,
        user_constraints: dict[str, Any] | None,
    ) -> dict[str, Any]:
        lower_goal = goal.lower()
        words = set(re.findall(r"\b[a-z0-9_-]+\b", lower_goal))

        # Explicit target files extracted from goal
        explicit_files = re.findall(
            r"\b[\w\.-]+\.(?:py|js|ts|tsx|jsx|html|css|json|sql|sh|md|yaml|yml)\b", lower_goal
        )
        if user_constraints and "target_files" in user_constraints:
            explicit_files.extend(user_constraints["target_files"])
        explicit_files = list(dict.fromkeys(explicit_files))

        # Workspace context signals
        ws_files: list[str] = []
        if workspace_context and "files" in workspace_context:
            ws_files = list(workspace_context["files"])

        # Detect Action Verbs
        action_verbs = {
            "create": bool(words & {"create", "build", "generate", "scaffold", "new"}),
            "add": bool(words & {"add", "include", "implement", "introduce"}),
            "modify": bool(words & {"modify", "edit", "change", "update", "patch", "fix", "debug"}),
            "refactor": bool(
                words & {"refactor", "restructure", "clean", "modularize", "reorganize"}
            ),
            "remove": bool(words & {"remove", "delete", "deprecate"}),
            "test": bool(words & {"test", "tests", "testing", "coverage", "verify", "unit-test"}),
            "migrate": bool(words & {"migrate", "migration", "alembic", "schema"}),
            "integrate": bool(words & {"integrate", "connect", "wire", "bridge"}),
        }

        # Technical Domains
        has_db = bool(
            words
            & {
                "database",
                "db",
                "postgres",
                "postgresql",
                "sql",
                "migration",
                "alembic",
                "schema",
                "models",
            }
        )
        has_cli = bool(
            words & {"cli", "command", "argparse", "click", "typer", "terminal", "utility"}
        )
        has_pipeline = bool(
            words
            & {
                "pipeline",
                "etl",
                "ingestion",
                "extractor",
                "transformer",
                "stream",
                "batch",
                "data",
            }
            and not has_cli
        )
        has_auth = bool(
            words
            & {"auth", "authentication", "login", "jwt", "oauth", "password", "session", "security"}
        )
        has_frontend = bool(
            words
            & {
                "frontend",
                "ui",
                "interface",
                "html",
                "css",
                "js",
                "javascript",
                "react",
                "vue",
                "landing",
                "page",
                "web",
            }
            or any(
                f.endswith((".html", ".css", ".js", ".jsx", ".tsx", ".vue")) for f in explicit_files
            )
        )
        has_backend = bool(
            words
            & {
                "backend",
                "api",
                "server",
                "endpoint",
                "fastapi",
                "flask",
                "django",
                "express",
                "rest",
                "service",
            }
            or any(f.endswith(".py") for f in explicit_files)
            or has_auth
        )
        has_tests_only = (
            bool(words & {"test", "tests"})
            and ("only" in words or "add tests" in lower_goal or "write tests" in lower_goal)
            and not (words & {"app", "feature", "build", "pipeline", "migration", "cli"})
        )
        is_function_mod = (
            (
                "function" in words
                or "method" in words
                or "one function" in lower_goal
                or "single function" in lower_goal
            )
            and bool(action_verbs["modify"] or action_verbs["add"])
            and not (words & {"full-stack", "fullstack", "pipeline", "migration"})
        )
        is_refactor = bool(action_verbs["refactor"]) and not (
            words & {"full-stack", "fullstack", "pipeline"}
        )

        # Recognize full-stack
        if (
            "full-stack" in lower_goal
            or "fullstack" in lower_goal
            or (has_frontend and has_backend and not has_tests_only)
        ):
            is_fullstack = True
        else:
            is_fullstack = False

        # Inferred Language/Framework
        is_python = bool(
            "python" in lower_goal
            or "fastapi" in lower_goal
            or "flask" in lower_goal
            or "django" in lower_goal
            or any(f.endswith(".py") for f in explicit_files)
            or any(f.endswith(".py") for f in ws_files)
        )
        is_node = bool(
            "node" in lower_goal
            or "javascript" in lower_goal
            or "npm" in lower_goal
            or any(f.endswith((".js", ".ts", ".jsx", ".tsx")) for f in explicit_files)
        )

        return {
            "goal": goal,
            "lower_goal": lower_goal,
            "words": words,
            "explicit_files": explicit_files,
            "workspace_files": ws_files,
            "action_verbs": action_verbs,
            "has_db": has_db,
            "has_cli": has_cli,
            "has_pipeline": has_pipeline,
            "has_auth": has_auth,
            "has_frontend": has_frontend,
            "has_backend": has_backend,
            "has_tests_only": has_tests_only,
            "is_function_mod": is_function_mod,
            "is_refactor": is_refactor,
            "is_fullstack": is_fullstack,
            "is_python": is_python,
            "is_node": is_node,
        }

    def _extract_concerns_and_build_dag(self, analysis: dict[str, Any]) -> list[CompiledTaskNode]:
        goal = analysis["goal"]
        explicit_files = analysis["explicit_files"]

        # Case 1: Tests only (no unrelated code generation tasks)
        if analysis["has_tests_only"]:
            target_files = explicit_files or [
                "tests/test_suite.py" if analysis["is_python"] else "test/app.test.js"
            ]
            eval_cmd = "python -m unittest" if analysis["is_python"] else "node --test"
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="test_generation",
                title="Author automated test suite",
                objective=f"Write comprehensive automated tests for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.CODE_GENERATION],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Execute authored test suite",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="objective_verification",
                title="Verify test execution",
                objective="Confirm all test cases execute and pass cleanly.",
                dependencies=["T1"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Objective verification of test run outcome",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2]

        # Case 2: Small targeted function modification / patch
        if analysis["is_function_mod"]:
            target_files = explicit_files or (["main.py"] if analysis["is_python"] else ["app.js"])
            eval_cmd = "python -m unittest" if analysis["is_python"] else "node --test"
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="code_modification",
                title="Modify targeted function",
                objective=f"Implement targeted function modification for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Verify function syntax and basic execution",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="objective_verification",
                title="Verify function modification",
                objective="Ensure modified function satisfies contract without regressions.",
                dependencies=["T1"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Verify function changes",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2]

        # Case 3: Refactoring existing module
        if analysis["is_refactor"]:
            target_files = explicit_files or ["module.py"]
            eval_cmd = "python -m unittest" if analysis["is_python"] else "node --test"
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="refactoring",
                title="Refactor targeted module",
                objective=f"Restructure code and improve modularity for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="regression_testing",
                title="Run regression tests",
                objective="Execute regression test suite to ensure refactoring preserves behavior.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_refactor.py" if analysis["is_python"] else "test_refactor.js"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Execute test suite against refactored code",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Final objective verification",
                objective="Verify refactoring integrity and clean exit code.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Objective verification of refactoring",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Compound Case: Database Migration + Authentication
        if analysis["has_db"] and analysis["has_auth"]:
            db_target_files = (
                [f for f in explicit_files if "migrat" in f or "model" in f or "db" in f]
                or ["alembic/versions/001_auth_migration.py", "models/user.py"]
            )
            auth_target_files = (
                [f for f in explicit_files if "auth" in f or "service" in f]
                or ["services/auth.py", "routes/auth.py"]
            )
            eval_cmd = "python -m unittest" if analysis["is_python"] else "node --test"
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="database_migration",
                title="Create authentication schema and migration",
                objective=f"Define schema changes for authentication in: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=db_target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="backend_development",
                title="Implement authentication service",
                objective=f"Implement authentication business logic and endpoints for: {goal}",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.CODE_REVIEW],
                target_files=auth_target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="test_generation",
                title="Author authentication integration tests",
                objective=(
                    "Write integration test suite covering auth flows and database persistence."
                ),
                dependencies=["T2"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=[
                    "tests/test_auth_migration.py" if analysis["is_python"] else "test/auth.test.js"
                ],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Run authentication & database integration tests",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t4 = CompiledTaskNode(
                task_id="T4",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify full authentication and database migration execution.",
                dependencies=["T3"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": eval_cmd},
                    "description": "Objective verification of auth and migration pipeline",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3, t4]

        # Case 4: Database Migration
        if analysis["has_db"] and not analysis["is_fullstack"]:
            target_files = explicit_files or ["alembic/versions/001_migration.py", "models.py"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="database_migration",
                title="Create database migration",
                objective=f"Define schema changes and database migration for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="schema_validation",
                title="Validate migration schema",
                objective="Validate database migration script syntax and schema constraints.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_migration.py"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_migration.py"},
                    "description": "Run schema validation tests",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify migration files and schema validity.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest"},
                    "description": "Objective verification of migration",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Case 5: CLI Utility
        if analysis["has_cli"]:
            target_files = explicit_files or ["cli.py"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="cli_development",
                title="Build CLI utility",
                objective=f"Implement command line interface parser and commands for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="cli_testing",
                title="Add CLI test suite",
                objective="Write tests verifying CLI argument parsing, flags, and exit codes.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_cli.py"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_cli.py"},
                    "description": "Run CLI automated test suite",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify CLI commands and execution exit codes.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_cli.py"},
                    "description": "Objective verification of CLI utility",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Case 6: Data Pipeline / ETL
        if analysis["has_pipeline"]:
            target_files = explicit_files or ["pipeline.py", "transformers.py"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="data_pipeline_development",
                title="Implement data pipeline",
                objective=f"Build ETL/data extraction and transformation pipeline for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="pipeline_testing",
                title="Add pipeline test suite",
                objective="Write tests verifying pipeline transformations and schema validation.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_pipeline.py"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_pipeline.py"},
                    "description": "Run data pipeline tests",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify pipeline execution, error handling, and test exit codes.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_pipeline.py"},
                    "description": "Objective verification of data pipeline",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Case 7: Auth addition or API feature addition
        if analysis["has_auth"] and not analysis["is_fullstack"]:
            target_files = explicit_files or ["auth.py", "main.py"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="backend_development",
                title="Implement authentication service",
                objective=(
                    f"Implement authentication endpoints, tokens, and middleware for: {goal}"
                ),
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="test_generation",
                title="Add authentication test suite",
                objective=(
                    "Write comprehensive unit tests for auth flows, tokens, and protected routes."
                ),
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_auth.py"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_auth.py"},
                    "description": "Run authentication test suite",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify auth endpoints, security headers, and test execution.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest test_auth.py"},
                    "description": "Objective verification of auth features",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Case 8: Full-Stack App (Frontend + Backend independent concerns)
        if analysis["is_fullstack"]:
            fe_files = [
                f for f in explicit_files if f.endswith((".html", ".css", ".js", ".jsx", ".tsx"))
            ] or ["index.html", "styles.css", "app.js"]
            be_files = [f for f in explicit_files if f.endswith((".py", ".sql"))] or [
                "server.py",
                "api.py",
            ]

            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="frontend_development",
                title="Build frontend interface",
                objective=f"Implement frontend user interface for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=fe_files,
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={},
                parallel_safe=True,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="backend_development",
                title="Build backend API",
                objective=f"Implement backend API service for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=be_files,
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={},
                parallel_safe=True,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="test_generation",
                title="Write test suite",
                objective="Add automated tests for backend API and frontend components.",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.CODE_GENERATION],
                target_files=["test_api.py", "app.test.js"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest"},
                    "description": "Run full-stack test suite",
                },
                parallel_safe=True,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t4 = CompiledTaskNode(
                task_id="T4",
                task_type="integration",
                title="Integrate frontend and backend",
                objective="Connect frontend UI to backend API and ensure contract alignment.",
                dependencies=["T1", "T2"],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=list(set(fe_files + be_files)),
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.MEDIUM,
            )
            t5 = CompiledTaskNode(
                task_id="T5",
                task_type="objective_verification",
                title="Objective verification",
                objective="Verify full-stack application implementation and test suite pass.",
                dependencies=["T3", "T4"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest"},
                    "description": "Objective verification of full-stack outcome",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3, t4, t5]

        # Case 9: Frontend only (landing page, UI app, calculator, etc.)
        if analysis["has_frontend"]:
            target_files = explicit_files or ["index.html", "styles.css", "script.js"]
            test_files = ["test/app.test.js"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="code_generation",
                title="Implement frontend application",
                objective=f"Implement frontend user interface for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="test_generation",
                title="Add automated test suite",
                objective="Add automated tests verifying frontend application functionality.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.CODE_GENERATION],
                target_files=test_files,
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "node --test"},
                    "description": "Run node test runner for frontend logic",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Final objective verification",
                objective="Verify workspace artifacts, test exit codes, and correctness.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "node --test"},
                    "description": "Objective verification of frontend outcome",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Case 10: Backend service only
        if analysis["has_backend"] or analysis["is_python"]:
            target_files = explicit_files or ["server.py", "api.py"]
            t1 = CompiledTaskNode(
                task_id="T1",
                task_type="backend_development",
                title="Implement backend service",
                objective=f"Build backend service logic for: {goal}",
                dependencies=[],
                required_capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[AgentCapability.DEBUGGING],
                target_files=target_files,
                target_files_ownership=TargetFileOwnership.KNOWN
                if explicit_files
                else TargetFileOwnership.PARTIAL,
                verification_requirements={},
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t2 = CompiledTaskNode(
                task_id="T2",
                task_type="test_generation",
                title="Add backend test suite",
                objective="Write automated unit tests for backend API.",
                dependencies=["T1"],
                required_capabilities=[
                    AgentCapability.TEST_GENERATION,
                    AgentCapability.FILE_EDITING,
                ],
                preferred_capabilities=[],
                target_files=["test_api.py"],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest"},
                    "description": "Run Python unit tests",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.SIMPLE,
            )
            t3 = CompiledTaskNode(
                task_id="T3",
                task_type="objective_verification",
                title="Final objective verification",
                objective="Verify backend service implementation and unit test execution.",
                dependencies=["T2"],
                required_capabilities=[AgentCapability.FILE_EDITING],
                preferred_capabilities=[],
                target_files=[],
                target_files_ownership=TargetFileOwnership.KNOWN,
                verification_requirements={
                    "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                    "criteria": {"command": "python -m unittest"},
                    "description": "Objective verification of backend outcome",
                },
                parallel_safe=False,
                estimated_complexity=ComplexityLevel.TRIVIAL,
            )
            return [t1, t2, t3]

        # Fallback: General Goal Structure
        ownership = TargetFileOwnership.KNOWN if explicit_files else TargetFileOwnership.UNKNOWN
        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Implement core functionality",
            objective=f"Build main implementation for: {goal}",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.DEBUGGING],
            target_files=explicit_files,
            target_files_ownership=ownership,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )
        t2 = CompiledTaskNode(
            task_id="T2",
            task_type="test_generation",
            title="Add test suite",
            objective="Add automated tests verifying implemented features.",
            dependencies=["T1"],
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.UNKNOWN,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "python -m unittest"},
                "description": "Run test suite",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )
        t3 = CompiledTaskNode(
            task_id="T3",
            task_type="objective_verification",
            title="Final verification",
            objective="Run verification and confirm all requirements are met.",
            dependencies=["T2"],
            required_capabilities=[AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "python -m unittest"},
                "description": "Final objective verification",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )
        return [t1, t2, t3]

    def _derive_parallel_safety(self, nodes: list[CompiledTaskNode]) -> None:
        """Derive parallel_safe dynamically from file ownership and target file overlap."""
        node_map = {n.task_id: n for n in nodes}

        def is_dependent(a_id: str, b_id: str) -> bool:
            visited: set[str] = set()
            stack = list(node_map[a_id].dependencies) if a_id in node_map else []
            while stack:
                curr = stack.pop()
                if curr == b_id:
                    return True
                if curr not in visited and curr in node_map:
                    visited.add(curr)
                    stack.extend(node_map[curr].dependencies)
            return False

        for i, node in enumerate(nodes):
            if (
                node.target_files_ownership != TargetFileOwnership.KNOWN
                or not node.target_files
                or node.task_type in ("integration", "objective_verification")
            ):
                node.parallel_safe = False
                continue

            has_concurrent_overlap = False
            for j, other in enumerate(nodes):
                if i == j:
                    continue
                is_dep = is_dependent(node.task_id, other.task_id) or is_dependent(
                    other.task_id, node.task_id
                )
                if is_dep:
                    continue
                if set(node.target_files) & set(other.target_files):
                    has_concurrent_overlap = True
                    break

            node.parallel_safe = not has_concurrent_overlap

    def _calculate_dag_depth(self, nodes: list[CompiledTaskNode]) -> int:
        node_map = {n.task_id: n for n in nodes}
        memo: dict[str, int] = {}

        def get_node_depth(task_id: str) -> int:
            if task_id in memo:
                return memo[task_id]
            node = node_map.get(task_id)
            if not node or not node.dependencies:
                memo[task_id] = 1
                return 1
            max_dep_depth = max(get_node_depth(dep) for dep in node.dependencies if dep in node_map)
            d = 1 + max_dep_depth
            memo[task_id] = d
            return d

        if not nodes:
            return 0
        return max(get_node_depth(n.task_id) for n in nodes)

    def _validate_and_bound_graph(self, nodes: list[CompiledTaskNode]) -> None:
        if len(nodes) > self.MAX_TASKS:
            raise ValueError(f"Task graph exceeds max task limit of {self.MAX_TASKS}")

        task_ids = [n.task_id for n in nodes]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs in compiled task graph")

        task_map = {n.to_task_spec().key: n.to_task_spec() for n in nodes}
        cycle = _detect_cycle(task_map)
        if cycle is not None:
            raise ValueError(f"Task graph contains cycle: {' -> '.join(cycle)}")

        depth = self._calculate_dag_depth(nodes)
        if depth > self.MAX_DEPTH:
            msg = f"Task graph depth {depth} exceeds max depth limit of {self.MAX_DEPTH}"
            raise ValueError(msg)


__all__ = [
    "CompiledTaskNode",
    "ComplexityLevel",
    "TargetFileOwnership",
    "TaskGraphCompilerV2",
]
