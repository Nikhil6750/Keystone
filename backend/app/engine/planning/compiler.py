"""Task Graph Compiler V2 (Agent-Independent DAG Decomposition).

Upgrades planning from fixed template lookup to a deterministic, bounded Task Graph Compiler.
Inputs: user goal, workspace/project context, deterministic project metadata, explicit user constraints.
Outputs: typed executable provider-neutral DAG (WorkflowPlan with enriched TaskSpecs).

Does NOT assign agent_type or take connected agents as required input.
WHO does the work is decided later by AgentOrganizationCompiler and Router.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, TaskSpec, WorkflowPlan, _detect_cycle


class TargetFileOwnership(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ComplexityLevel(str, Enum):
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
    """Agent-independent deterministic Task Graph Compiler."""

    MAX_TASKS = 10
    MAX_DEPTH = 5

    def compile(
        self,
        goal: str,
        workspace_context: dict[str, Any] | None = None,
        project_metadata: dict[str, Any] | None = None,
        user_constraints: dict[str, Any] | None = None,
    ) -> list[CompiledTaskNode]:
        """Compile a user goal into a typed executable DAG task graph."""
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")

        goal_clean = goal.strip()
        lower_goal = goal_clean.lower()
        complexity = self._classify_complexity(lower_goal, workspace_context, project_metadata)

        nodes: list[CompiledTaskNode] = []

        if complexity == ComplexityLevel.TRIVIAL or "calculator" in lower_goal:
            nodes = self._compile_calculator_or_simple(goal_clean, lower_goal)
        elif "full-stack" in lower_goal or "task tracker" in lower_goal or "fullstack" in lower_goal:
            nodes = self._compile_fullstack_app(goal_clean, lower_goal)
        elif complexity == ComplexityLevel.SIMPLE:
            nodes = self._compile_simple_task(goal_clean, lower_goal)
        else:
            nodes = self._compile_medium_or_large(goal_clean, lower_goal, complexity)

        self._validate_and_bound_graph(nodes)

        return nodes

    def _classify_complexity(
        self,
        lower_goal: str,
        workspace_context: dict[str, Any] | None,
        project_metadata: dict[str, Any] | None,
    ) -> ComplexityLevel:
        signals = 0
        if any(w in lower_goal for w in ["full-stack", "fullstack", "frontend", "backend", "database", "api"]):
            signals += 2
        if any(w in lower_goal for w in ["test", "tests", "unit test", "integration"]):
            signals += 1
        if any(w in lower_goal for w in ["auth", "security", "migration", "deployment"]):
            signals += 2

        words = len(lower_goal.split())
        if words < 6 and signals == 0:
            return ComplexityLevel.TRIVIAL
        elif signals <= 1 and words < 20:
            return ComplexityLevel.SIMPLE
        elif signals <= 3:
            return ComplexityLevel.MEDIUM
        else:
            return ComplexityLevel.LARGE

    def _compile_calculator_or_simple(
        self, goal: str, lower_goal: str
    ) -> list[CompiledTaskNode]:
        """Simple calculator or small app decomposition.

        Produces:
        T1: Implement calculator application (target_files: index.html, styles.css, script.js)
        T2: Add automated tests (depends on T1, target_files: calculator.test.js)
        T3: Objective verification (depends on T2)
        """
        is_calc = "calculator" in lower_goal
        t1_files = ["index.html", "styles.css", "script.js"] if is_calc else []
        t1_ownership = TargetFileOwnership.KNOWN if is_calc else TargetFileOwnership.UNKNOWN

        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Implement calculator application" if is_calc else "Implement application logic",
            objective="Build the core HTML, CSS, and JS calculator implementation with keyboard and responsive UI." if is_calc else goal,
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.DEBUGGING],
            target_files=t1_files,
            target_files_ownership=t1_ownership,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )

        t2_files = ["calculator.test.js", "test/calculator.test.js"] if is_calc else []
        t2_ownership = TargetFileOwnership.KNOWN if is_calc else TargetFileOwnership.UNKNOWN

        t2 = CompiledTaskNode(
            task_id="T2",
            task_type="test_generation",
            title="Add automated tests",
            objective="Write automated tests using Node's built-in test runner to verify calculator functionality.",
            dependencies=["T1"],
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.CODE_GENERATION],
            target_files=t2_files,
            target_files_ownership=t2_ownership,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "node --test"},
                "description": "Run Node tests to verify calculation logic",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )

        t3 = CompiledTaskNode(
            task_id="T3",
            task_type="objective_verification",
            title="Final objective verification",
            objective="Verify workspace artifacts, test exit codes, and application correctness.",
            dependencies=["T2"],
            required_capabilities=[AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "node --test"},
                "description": "Objective verification of overall outcome",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )

        return [t1, t2, t3]

    def _compile_fullstack_app(
        self, goal: str, lower_goal: str
    ) -> list[CompiledTaskNode]:
        """Full-stack app decomposition with independent parallel tasks.

        Frontend (T1), Backend (T2), and Tests (T3) have non-overlapping target files and can run concurrently if dependencies allow.
        """
        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="frontend_development",
            title="Build frontend interface",
            objective="Implement HTML/CSS/JS frontend interface for task tracker.",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=["index.html", "styles.css", "app.js"],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={},
            parallel_safe=True,
            estimated_complexity=ComplexityLevel.MEDIUM,
        )

        t2 = CompiledTaskNode(
            task_id="T2",
            task_type="backend_development",
            title="Build backend API",
            objective="Implement Python API backend for task management.",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.DEBUGGING],
            target_files=["server.py", "api.py"],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={},
            parallel_safe=True,
            estimated_complexity=ComplexityLevel.MEDIUM,
        )

        t3 = CompiledTaskNode(
            task_id="T3",
            task_type="test_generation",
            title="Write backend & frontend tests",
            objective="Add unit tests for backend API and frontend logic.",
            dependencies=[],
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.CODE_GENERATION],
            target_files=["test_api.py", "test_app.js"],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "python -m unittest"},
                "description": "Run API tests",
            },
            parallel_safe=True,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )

        t4 = CompiledTaskNode(
            task_id="T4",
            task_type="integration",
            title="Integrate frontend and backend",
            objective="Connect frontend UI to backend API endpoints.",
            dependencies=["T1", "T2"],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=["index.html", "app.js", "server.py"],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.MEDIUM,
        )

        t5 = CompiledTaskNode(
            task_id="T5",
            task_type="objective_verification",
            title="Objective verification",
            objective="Verify task tracker implementation and test execution.",
            dependencies=["T3", "T4"],
            required_capabilities=[AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "python -m unittest"},
                "description": "Objective verification of task tracker",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )

        return [t1, t2, t3, t4, t5]

    def _compile_simple_task(
        self, goal: str, lower_goal: str
    ) -> list[CompiledTaskNode]:
        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Execute goal",
            objective=goal,
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.UNKNOWN,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.SIMPLE,
        )
        t2 = CompiledTaskNode(
            task_id="T2",
            task_type="objective_verification",
            title="Verify result",
            objective="Verify outcome of executed task.",
            dependencies=["T1"],
            required_capabilities=[AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.KNOWN,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )
        return [t1, t2]

    def _compile_medium_or_large(
        self, goal: str, lower_goal: str, complexity: ComplexityLevel
    ) -> list[CompiledTaskNode]:
        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Implement core functionality",
            objective=f"Build main implementation for: {goal}",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.DEBUGGING],
            target_files=[],
            target_files_ownership=TargetFileOwnership.UNKNOWN,
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=complexity,
        )
        t2 = CompiledTaskNode(
            task_id="T2",
            task_type="test_generation",
            title="Add test suite",
            objective="Add comprehensive tests for implemented features.",
            dependencies=["T1"],
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=[],
            target_files_ownership=TargetFileOwnership.UNKNOWN,
            verification_requirements={},
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
            verification_requirements={},
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )
        return [t1, t2, t3]

    def _validate_and_bound_graph(self, nodes: list[CompiledTaskNode]) -> None:
        """Enforce task bounds, cycle detection, and duplicate task detection."""
        if len(nodes) > self.MAX_TASKS:
            raise ValueError(f"Task graph exceeds max task limit of {self.MAX_TASKS}")

        task_ids = [n.task_id for n in nodes]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs in compiled task graph")

        task_map = {n.to_task_spec().key: n.to_task_spec() for n in nodes}
        cycle = _detect_cycle(task_map)
        if cycle is not None:
            raise ValueError(f"Task graph contains cycle: {' -> '.join(cycle)}")


__all__ = [
    "CompiledTaskNode",
    "ComplexityLevel",
    "TargetFileOwnership",
    "TaskGraphCompilerV2",
]
