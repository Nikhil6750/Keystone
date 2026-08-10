"""Tests for Stage 8C.3A Dynamic Agent Connection Foundation.

Verifies provider-neutral, extensible connection and agent domain entities,
referential integrity, secret boundary enforcement, Router integration, and REST APIs.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.planning import TaskSpec
from app.engine.connections.bridge import ConnectedAgentCandidateBridge
from app.engine.connections.exceptions import (
    ConnectionHasDependentAgentsError,
    ConnectionNotFoundError,
    DuplicateAgentError,
    DuplicateConnectionError,
)
from app.engine.connections.models import (
    AgentConnection,
    AgentConnectionCreate,
    AgentConnectionStatus,
    ConnectedAgentCreate,
    ConnectionKind,
)
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
)
from app.engine.orchestration.runtime import RegistryCandidateProvider
from app.engine.registry import ExecutorRegistry
from app.engine.routing.request_builder import build_routing_request
from app.engine.routing.router import Router
from app.main import app
from tests.support.executors import RecordingExecutor


@pytest.fixture
def conn_repo() -> AgentConnectionRepository:
    return AgentConnectionRepository()


@pytest.fixture
def agent_repo() -> ConnectedAgentRepository:
    return ConnectedAgentRepository()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# --- Domain Model Tests ------------------------------------------------------


def test_1_arbitrary_provider_runtime_string_accepted() -> None:
    conn = AgentConnection(
        connection_id="conn-1",
        display_name="Acme Custom Engine Connection",
        connection_kind="custom",
        provider_or_runtime="acme-internal-engine",
    )
    assert conn.provider_or_runtime == "acme-internal-engine"
    assert conn.connection_kind == "custom"


def test_2_arbitrary_connection_id_accepted() -> None:
    conn = AgentConnection(
        connection_id="my-custom-corp-connection-999",
        display_name="Corp Connection",
        provider_or_runtime="corp-runtime",
    )
    assert conn.connection_id == "my-custom-corp-connection-999"


def test_3_arbitrary_agent_id_accepted(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="openrouter-personal",
            display_name="OpenRouter Personal",
            provider_or_runtime="openrouter",
        )
    )
    agent = agent_repo.register(
        ConnectedAgentCreate(
            agent_id="my-openrouter-qwen-agent",
            display_name="My Qwen Agent",
            connection_id="openrouter-personal",
        ),
        conn_repo,
    )
    assert agent.agent_id == "my-openrouter-qwen-agent"


def test_4_5_6_one_connection_supports_multiple_agents_and_models(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="openrouter-personal",
            display_name="OpenRouter Personal",
            provider_or_runtime="openrouter",
        )
    )
    a1 = agent_repo.register(
        ConnectedAgentCreate(
            agent_id="qwen-coder",
            display_name="Qwen Coder",
            connection_id="openrouter-personal",
            model_id="qwen/qwen-2.5-coder-32b-instruct",
            capabilities=[AgentCapability.CODE_GENERATION],
        ),
        conn_repo,
    )
    a2 = agent_repo.register(
        ConnectedAgentCreate(
            agent_id="qwen-reviewer",
            display_name="Qwen Reviewer",
            connection_id="openrouter-personal",
            model_id="qwen/qwen-2.5-coder-32b-instruct",
            capabilities=[AgentCapability.CODE_REVIEW],
        ),
        conn_repo,
    )
    a3 = agent_repo.register(
        ConnectedAgentCreate(
            agent_id="deepseek-debugger",
            display_name="DeepSeek Debugger",
            connection_id="openrouter-personal",
            model_id="deepseek/deepseek-r1",
            capabilities=[AgentCapability.DEBUGGING],
        ),
        conn_repo,
    )

    agents = agent_repo.list(connection_id="openrouter-personal")
    assert len(agents) == 3
    assert {a.agent_id for a in agents} == {"deepseek-debugger", "qwen-coder", "qwen-reviewer"}
    assert a1.model_id == a2.model_id == "qwen/qwen-2.5-coder-32b-instruct"
    assert a3.model_id == "deepseek/deepseek-r1"


def test_7_custom_company_runtime_works(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn = conn_repo.register(
        AgentConnectionCreate(
            connection_id="corp-runtime",
            display_name="Corp Security Engine",
            connection_kind=ConnectionKind.CUSTOM,
            provider_or_runtime="acme-internal-engine",
        )
    )
    agent = agent_repo.register(
        ConnectedAgentCreate(
            agent_id="corp-security-reviewer",
            display_name="Corp Security Reviewer",
            connection_id="corp-runtime",
            capabilities=[AgentCapability.CODE_REVIEW],
        ),
        conn_repo,
    )
    assert conn.provider_or_runtime == "acme-internal-engine"
    assert agent.agent_id == "corp-security-reviewer"


# --- Referential Integrity & Validation Tests --------------------------------


def test_8_nonexistent_connection_reference_rejected(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    with pytest.raises(ConnectionNotFoundError):
        agent_repo.register(
            ConnectedAgentCreate(
                agent_id="orphan-agent",
                display_name="Orphan Agent",
                connection_id="does-not-exist",
            ),
            conn_repo,
        )


def test_20_duplicate_connection_safe_typed_failure(
    conn_repo: AgentConnectionRepository,
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-x",
            display_name="Conn X",
            provider_or_runtime="provider-x",
        )
    )
    with pytest.raises(DuplicateConnectionError):
        conn_repo.register(
            AgentConnectionCreate(
                connection_id="conn-x",
                display_name="Conn X Duplicate",
                provider_or_runtime="provider-x",
            )
        )


def test_21_duplicate_agent_safe_typed_failure(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-x",
            display_name="Conn X",
            provider_or_runtime="provider-x",
        )
    )
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="agent-x",
            display_name="Agent X",
            connection_id="conn-x",
        ),
        conn_repo,
    )
    with pytest.raises(DuplicateAgentError):
        agent_repo.register(
            ConnectedAgentCreate(
                agent_id="agent-x",
                display_name="Agent X Duplicate",
                connection_id="conn-x",
            ),
            conn_repo,
        )


def test_22_dependent_connection_deletion_safe(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-x",
            display_name="Conn X",
            provider_or_runtime="provider-x",
        )
    )
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="agent-x",
            display_name="Agent X",
            connection_id="conn-x",
        ),
        conn_repo,
    )

    with pytest.raises(ConnectionHasDependentAgentsError) as exc_info:
        conn_repo.delete("conn-x", agent_repo)

    assert exc_info.value.dependent_agent_ids == ["agent-x"]
    assert conn_repo.get("conn-x") is not None


# --- Secret Boundary Tests ----------------------------------------------------


def test_23_24_25_26_secret_fields_strictly_forbidden() -> None:
    with pytest.raises(ValidationError) as exc1:
        AgentConnectionCreate.model_validate(
            {
                "connection_id": "c1",
                "display_name": "C1",
                "provider_or_runtime": "p1",
                "api_key": "secret-123",
            }
        )
    assert "extra_fields" in str(exc1.value) or "api_key" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        AgentConnectionCreate.model_validate(
            {
                "connection_id": "c1",
                "display_name": "C1",
                "provider_or_runtime": "p1",
                "metadata": {"api_key": "secret-in-metadata"},
            }
        )
    assert "secret-bearing" in str(exc2.value)

    with pytest.raises(ValidationError) as exc3:
        ConnectedAgentCreate.model_validate(
            {
                "agent_id": "a1",
                "display_name": "A1",
                "connection_id": "c1",
                "metadata": {"token": "secret-token"},
            }
        )
    assert "secret-bearing" in str(exc3.value)


# --- Router & Registry Bridge Tests -------------------------------------------


def test_9_10_11_12_13_14_15_router_bridge_and_eligibility(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    # 1. Register Active Connection + 2 Agents
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="active-conn",
            display_name="Active Connection",
            provider_or_runtime="custom-runtime",
            status=AgentConnectionStatus.CONNECTED,
        )
    )
    # Disabled connection
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="disabled-conn",
            display_name="Disabled Connection",
            provider_or_runtime="custom-runtime",
            status=AgentConnectionStatus.DISABLED,
        )
    )

    # Agent 1: Enabled + Code Gen
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="code-agent",
            display_name="Code Agent",
            connection_id="active-conn",
            capabilities=[AgentCapability.CODE_GENERATION],
            enabled=True,
        ),
        conn_repo,
    )
    # Agent 2: Disabled agent
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="disabled-agent",
            display_name="Disabled Agent",
            connection_id="active-conn",
            capabilities=[AgentCapability.CODE_GENERATION],
            enabled=False,
        ),
        conn_repo,
    )
    # Agent 3: Under disabled connection
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="unreachable-agent",
            display_name="Unreachable Agent",
            connection_id="disabled-conn",
            capabilities=[AgentCapability.CODE_GENERATION],
            enabled=True,
        ),
        conn_repo,
    )

    bridge = ConnectedAgentCandidateBridge(conn_repo, agent_repo)
    descriptors = bridge.get_descriptors()

    assert "code-agent" in descriptors
    assert "disabled-agent" not in descriptors  # disabled agent excluded
    assert "unreachable-agent" not in descriptors  # disabled connection excluded

    # Test ExecutorRegistry integration
    executor_reg = ExecutorRegistry()
    executor_reg.register("code-agent", RecordingExecutor())

    from app.adapters.connection import (
        AgentConnectionCache,
        AgentConnectionState,
        AuthenticationStatus,
        ConnectionStatus,
        InstallationStatus,
        now_utc,
    )

    cache = AgentConnectionCache(cache_seconds=300)
    cache.set(
        "code-agent",
        AgentConnectionState(
            agent_type="code-agent",
            display_name="Code Agent",
            executable_name="",
            enabled=True,
            installation_status=InstallationStatus.INSTALLED,
            authentication_status=AuthenticationStatus.AUTHENTICATED,
            connection_status=ConnectionStatus.CONNECTED,
            registered=True,
            execution_mode="local_cli",
            version=None,
            last_checked_at=now_utc(),
            reason="connected",
        ),
    )

    candidate_provider = RegistryCandidateProvider(
        registry=executor_reg,
        agent_types=("code-agent", "unregistered-agent"),
        descriptors=descriptors,
        connection_cache=cache,
    )
    candidates = candidate_provider.candidates()

    assert len(candidates) == 1
    assert candidates[0].descriptor.agent_type == "code-agent"
    assert candidates[0].status == AgentStatus.AVAILABLE

    # Test Router authority & capability matching
    router = Router()
    
    # Task requires CODE_GENERATION -> matches code-agent
    task_match = TaskSpec(
        key="t1",
        name="impl",
        task_type="implementation",
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    req_match = build_routing_request(task_match, candidate_agent_types=["code-agent"])
    decision_match = router.route(req_match, candidates)
    assert decision_match.selected_agent_type == "code-agent"

    # Task requires TEST_EXECUTION -> code-agent lacks capability -> Router rejects
    task_mismatch = TaskSpec(
        key="t2",
        name="test",
        task_type="testing",
        required_capabilities=[AgentCapability.TEST_EXECUTION],
    )
    req_mismatch = build_routing_request(task_mismatch, candidate_agent_types=["code-agent"])
    decision_mismatch = router.route(req_mismatch, candidates)
    assert decision_mismatch.selected_agent_type is None
    assert any(
        c.agent_type == "code-agent" and not c.eligible for c in decision_mismatch.candidates
    )


def test_16_17_deterministic_ordering(
    conn_repo: AgentConnectionRepository, agent_repo: ConnectedAgentRepository
) -> None:
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-z",
            display_name="Z",
            provider_or_runtime="p",
        )
    )
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-a",
            display_name="A",
            provider_or_runtime="p",
        )
    )
    assert [c.connection_id for c in conn_repo.list()] == ["conn-a", "conn-z"]

    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="agent-z",
            display_name="Z",
            connection_id="conn-a",
        ),
        conn_repo,
    )
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="agent-a",
            display_name="A",
            connection_id="conn-a",
        ),
        conn_repo,
    )
    assert [a.agent_id for a in agent_repo.list()] == ["agent-a", "agent-z"]


# --- REST API Endpoint Tests --------------------------------------------------


def test_18_19_27_28_29_api_endpoints_round_trip(client: TestClient) -> None:
    # 1. Create Connection
    res1 = client.post(
        "/api/v1/agent-connections",
        json={
            "connection_id": "openrouter-personal",
            "display_name": "OpenRouter Personal",
            "connection_kind": "api",
            "provider_or_runtime": "openrouter",
        },
    )
    assert res1.status_code == 201
    assert res1.json()["connection_id"] == "openrouter-personal"

    # 2. Create Agent
    res2 = client.post(
        "/api/v1/connected-agents",
        json={
            "agent_id": "my-openrouter-qwen-agent",
            "display_name": "My Qwen Agent",
            "connection_id": "openrouter-personal",
            "model_id": "qwen/qwen-2.5-coder-32b-instruct",
            "capabilities": ["code_generation"],
        },
    )
    assert res2.status_code == 201
    body2 = res2.json()
    assert body2["agent_id"] == "my-openrouter-qwen-agent"
    assert body2["model_id"] == "qwen/qwen-2.5-coder-32b-instruct"

    # 3. Get Agent (Round-trip check)
    res3 = client.get("/api/v1/connected-agents/my-openrouter-qwen-agent")
    assert res3.status_code == 200
    assert res3.json()["display_name"] == "My Qwen Agent"

    # 4. Unknown Connection 404
    res4 = client.get("/api/v1/agent-connections/unknown-conn")
    assert res4.status_code == 404

    # 5. Unknown Agent 404
    res5 = client.get("/api/v1/connected-agents/unknown-agent")
    assert res5.status_code == 404

    # 6. Reject Secret in POST
    res6 = client.post(
        "/api/v1/agent-connections",
        json={
            "connection_id": "bad-conn",
            "display_name": "Bad",
            "provider_or_runtime": "p",
            "api_key": "sk-secret",
        },
    )
    assert res6.status_code == 422
