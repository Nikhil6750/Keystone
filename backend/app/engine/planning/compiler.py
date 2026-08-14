"""Task Graph Compiler V2 (Agent-Independent DAG Decomposition).

Upgrades planning from fixed template lookup to a deterministic, bounded Task Graph Compiler.
Inputs: user goal, workspace/project context, project metadata, explicit user constraints.
Outputs: typed executable provider-neutral DAG (WorkflowPlan with enriched TaskSpecs).

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

        # Detect structural domains and requested files
        frontend_keywords = {
            "html", "css", "js", "javascript", "frontend",
            "ui", "web", "page", "dashboard", "calculator",
        }
        backend_keywords = {
            "python", "api", "backend", "server", "express", "fastapi", "flask", "endpoint", "rest"
        }

        words = set(re.findall(r"\b\w+\b", lower_goal))
        has_frontend = bool(words & frontend_keywords)
        has_backend = bool(words & backend_keywords)

        # Extract explicit file paths requested in goal
        explicit_files = re.findall(r"\b[\w\.-]+\.(?:html|css|js|py|ts|jsx|tsx|json)\b", lower_goal)

        nodes: list[CompiledTaskNode] = []

        if has_frontend and has_backend:
            nodes = self._compile_fullstack_structure(goal_clean, explicit_files)
        elif has_frontend or any(f.endswith((".html", ".css", ".js")) for f in explicit_files):
            nodes = self._compile_frontend_structure(goal_clean, explicit_files)
        elif has_backend or any(f.endswith(".py") for f in explicit_files):
            nodes = self._compile_backend_structure(goal_clean, explicit_files)
        elif complexity == ComplexityLevel.TRIVIAL or complexity == ComplexityLevel.SIMPLE:
            nodes = self._compile_simple_structure(goal_clean, explicit_files)
        else:
            nodes = self._compile_medium_structure(goal_clean, explicit_files, complexity)

        # Enforce parallel safety derivation from file ownership & overlaps
        self._derive_parallel_safety(nodes)

        # Validate bounds (tasks count, duplicate IDs, cycles, MAX_DEPTH)
        self._validate_and_bound_graph(nodes)

        return nodes

    def _derive_parallel_safety(self, nodes: list[CompiledTaskNode]) -> None:
        """Derive parallel_safe dynamically from file ownership and target file overlap."""
        node_map = {n.task_id: n for n in nodes}

        def is_dependent(a_id: str, b_id: str) -> bool:
            """Check if a_id depends on b_id (directly or transitively)."""
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
            if node.target_files_ownership != TargetFileOwnership.KNOWN or not node.target_files:
                node.parallel_safe = False
                continue

            # Check target_file overlaps with concurrent (non-dependent) sibling nodes
            has_concurrent_overlap = False
            for j, other in enumerate(nodes):
                if i == j:
                    continue
                # If A depends on B or B depends on A, they are sequential, not concurrent
                is_dep = is_dependent(node.task_id, other.task_id) or is_dependent(
                    other.task_id, node.task_id
                )
                if is_dep:
                    continue
                # If two non-dependent nodes share target files, they cannot run concurrently safely
                if set(node.target_files) & set(other.target_files):
                    has_concurrent_overlap = True
                    break

            node.parallel_safe = not has_concurrent_overlap

    def _classify_complexity(
        self,
        lower_goal: str,
        workspace_context: dict[str, Any] | None,
        project_metadata: dict[str, Any] | None,
    ) -> ComplexityLevel:
        signals = 0
        fs_words = ["full-stack", "fullstack", "frontend", "backend", "database", "api"]
        if any(w in lower_goal for w in fs_words):
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

    def _compile_frontend_structure(
        self, goal: str, explicit_files: list[str]
    ) -> list[CompiledTaskNode]:
        default_fe = ["index.html", "styles.css", "script.js"]
        target_files = list(dict.fromkeys(explicit_files)) if explicit_files else default_fe

        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Implement frontend application",
            objective=f"Implement frontend user interface for: {goal}",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
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
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.CODE_GENERATION],
            target_files=["test/app.test.js"],
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
            objective="Verify workspace artifacts, test exit codes, and application correctness.",
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

    def _compile_fullstack_structure(
        self, goal: str, explicit_files: list[str]
    ) -> list[CompiledTaskNode]:
        default_fe = ["index.html", "styles.css", "app.js"]
        fe_files = [f for f in explicit_files if f.endswith((".html", ".css", ".js"))] or default_fe
        be_files = [f for f in explicit_files if f.endswith(".py")] or ["server.py", "api.py"]

        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="frontend_development",
            title="Build frontend interface",
            objective="Implement frontend user interface.",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
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
            objective="Implement backend API logic.",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
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
            objective="Verify full-stack application implementation and test execution.",
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

    def _compile_backend_structure(
        self, goal: str, explicit_files: list[str]
    ) -> list[CompiledTaskNode]:
        be_files = explicit_files or ["server.py", "api.py"]

        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="backend_development",
            title="Implement backend service",
            objective=f"Build backend service logic for: {goal}",
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[AgentCapability.DEBUGGING],
            target_files=be_files,
            target_files_ownership=TargetFileOwnership.KNOWN,
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
            required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
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

    def _compile_simple_structure(
        self, goal: str, explicit_files: list[str]
    ) -> list[CompiledTaskNode]:
        ownership = TargetFileOwnership.KNOWN if explicit_files else TargetFileOwnership.UNKNOWN
        t1 = CompiledTaskNode(
            task_id="T1",
            task_type="code_generation",
            title="Execute task goal",
            objective=goal,
            dependencies=[],
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            preferred_capabilities=[],
            target_files=explicit_files,
            target_files_ownership=ownership,
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
            verification_requirements={
                "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
                "criteria": {"command": "python -m unittest"},
                "description": "Verify task outcome",
            },
            parallel_safe=False,
            estimated_complexity=ComplexityLevel.TRIVIAL,
        )
        return [t1, t2]

    def _compile_medium_structure(
        self, goal: str, explicit_files: list[str], complexity: ComplexityLevel
    ) -> list[CompiledTaskNode]:
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

    def _calculate_dag_depth(self, nodes: list[CompiledTaskNode]) -> int:
        """Calculate the longest path (depth) in the task graph DAG."""
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
        """Enforce task bounds, cycle detection, duplicate task detection, and MAX_DEPTH."""
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
