"""Unit tests for AgentOrganizationCompiler (Team Assembly & Agent Routing)."""

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.engine.planning.compiler import CompiledTaskNode, TargetFileOwnership
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.organization import AgentOrganizationCompiler
from app.resilience.circuit_breaker import CircuitState


def _make_candidate(agent_type: str, capabilities: list[AgentCapability]) -> CandidateAgent:
    descriptor = AgentDescriptor(
        agent_type=agent_type,
        display_name=f"Agent {agent_type}",
        capabilities=capabilities,
    )
    return CandidateAgent(
        descriptor=descriptor,
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )


def test_organization_compiler_uses_smallest_effective_team_for_simple_graph() -> None:
    caps = [
        AgentCapability.CODE_GENERATION,
        AgentCapability.FILE_EDITING,
        AgentCapability.TEST_GENERATION,
    ]
    codex = _make_candidate("codex", caps)
    claude = _make_candidate("claude_code", caps)

    compiler = AgentOrganizationCompiler()

    t1 = CompiledTaskNode(
        task_id="T1",
        task_type="code_generation",
        title="Calculator logic",
        objective="Build calculator",
        required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
    )
    t2 = CompiledTaskNode(
        task_id="T2",
        task_type="test_generation",
        title="Calculator tests",
        objective="Write tests",
        dependencies=["T1"],
        required_capabilities=[AgentCapability.TEST_GENERATION, AgentCapability.FILE_EDITING],
    )

    team = compiler.assemble_team([t1, t2], [codex, claude])

    # Simple 2-task sequential graph -> 1 best agent is optimal
    assert len(team.selected_agent_ids) == 1
    selected = team.selected_agent_ids[0]
    assert team.assignments["T1"].selected_agent_type == selected
    assert team.assignments["T2"].selected_agent_type == selected


def test_organization_compiler_distributes_independent_parallel_tasks() -> None:
    code_caps = [AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING]
    codex = _make_candidate("codex", code_caps)
    antigravity = _make_candidate("antigravity", code_caps)

    compiler = AgentOrganizationCompiler()

    t1 = CompiledTaskNode(
        task_id="T1",
        task_type="frontend_development",
        title="Frontend",
        objective="HTML/CSS",
        target_files=["index.html", "styles.css"],
        target_files_ownership=TargetFileOwnership.KNOWN,
        parallel_safe=True,
        required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
    )
    t2 = CompiledTaskNode(
        task_id="T2",
        task_type="backend_development",
        title="Backend",
        objective="Python API",
        target_files=["server.py"],
        target_files_ownership=TargetFileOwnership.KNOWN,
        parallel_safe=True,
        required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
    )

    team = compiler.assemble_team([t1, t2], [codex, antigravity])

    # Independent parallel tasks -> distributed across available agents
    assert set(team.selected_agent_ids) == {"codex", "antigravity"}
    assert team.assignments["T1"].selected_agent_type != team.assignments["T2"].selected_agent_type
