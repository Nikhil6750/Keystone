"""Tests for Stage 8C.3A Dynamic Agent Connection Foundation (Hardened).

Verifies provider-neutral connection and agent entities, referential integrity,
secret boundary enforcement, deadlock-free concurrency, mutation leakage prevention,
Router integration, and REST APIs.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import (
    get_agent_connection_repository,
    get_connected_agent_repository,
)
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
    MAX_ID_LENGTH,
    MAX_METADATA_ITEMS,
    MAX_NAME_LENGTH,
    AgentConnection,
    AgentConnectionCreate,
    AgentConnectionStatus,
    AgentConnectionUpdate,
    ConnectedAgentCreate,
    ConnectionKind,
)
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
    ConnectionRegistryCoordinator,
)
from app.engine.orchestration.runtime import RegistryCandidateProvider
from app.engine.registry import ExecutorRegistry
from app.engine.routing.request_builder import build_routing_request
from app.engine.routing.router import Router
from app.main import app
from app.schemas.errors import APIErrorCode
from tests.support.executors import RecordingExecutor


@pytest.fixture
def fresh_repos() -> tuple[AgentConnectionRepository, ConnectedAgentRepository]:
    coord = ConnectionRegistryCoordinator()
    conn_repo = AgentConnectionRepository(coordinator=coord)
    agent_repo = ConnectedAgentRepository(coordinator=coord)
    return conn_repo, agent_repo


@pytest.fixture
def client(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> TestClient:
    conn_repo, agent_repo = fresh_repos
    app.dependency_overrides[get_agent_connection_repository] = lambda: conn_repo
    app.dependency_overrides[get_connected_agent_repository] = lambda: agent_repo
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# --- Domain Model & Identifier Bounds -----------------------------------------


def test_1_arbitrary_provider_runtime_string_accepted() -> None:
    conn = AgentConnection(
        connection_id="conn-1",
        display_name="Acme Custom Engine Connection",
        connection_kind=ConnectionKind.CUSTOM,
        provider_or_runtime="acme-internal-engine",
    )
    assert conn.provider_or_runtime == "acme-internal-engine"
    assert conn.connection_kind == ConnectionKind.CUSTOM


def test_2_arbitrary_connection_id_accepted() -> None:
    conn = AgentConnection(
        connection_id="my-custom-corp-connection-999",
        display_name="Corp Connection",
        provider_or_runtime="corp-runtime",
    )
    assert conn.connection_id == "my-custom-corp-connection-999"


def test_3_arbitrary_agent_id_accepted(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
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
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
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
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
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


def test_unknown_connection_kind_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentConnectionCreate.model_validate(
            {
                "connection_id": "c1",
                "display_name": "C1",
                "connection_kind": "magic_wand",
                "provider_or_runtime": "p1",
            }
        )
    assert "Input should be" in str(exc.value) or "connection_kind" in str(exc.value)


def test_identifier_bounds_enforced() -> None:
    oversized_id = "x" * (MAX_ID_LENGTH + 1)
    oversized_name = "n" * (MAX_NAME_LENGTH + 1)

    with pytest.raises(ValidationError):
        AgentConnectionCreate(
            connection_id=oversized_id,
            display_name="Valid Name",
            provider_or_runtime="p1",
        )

    with pytest.raises(ValidationError):
        AgentConnectionCreate(
            connection_id="valid-id",
            display_name=oversized_name,
            provider_or_runtime="p1",
        )


# --- Secret Boundary & Metadata Hardening ------------------------------------


def test_secret_key_bypasses_rejected() -> None:
    # 1. Nested metadata object rejected
    with pytest.raises(ValidationError) as exc1:
        AgentConnectionCreate.model_validate(
            {
                "connection_id": "c1",
                "display_name": "C1",
                "provider_or_runtime": "p1",
                "metadata": {"config": {"api_key": "sk-123"}},
            }
        )
    assert isinstance(exc1.value, ValidationError)

    # 2. Normalized secret keys rejected (hyphen, uppercase, mixed)
    for bad_key in [
        "api_key",
        "API_KEY",
        "api-key",
        "x-api-key",
        "access_token",
        "ACCESS-TOKEN",
        "authorization",
        "bearer-token",
        "client_secret",
        "private-key",
        "password",
    ]:
        with pytest.raises(ValidationError) as exc2:
            AgentConnectionCreate.model_validate(
                {
                    "connection_id": "c1",
                    "display_name": "C1",
                    "provider_or_runtime": "p1",
                    "metadata": {bad_key: "some-val"},
                }
            )
        assert "secret-bearing" in str(exc2.value)


def test_metadata_bounds_enforced() -> None:
    # Exceed items
    too_many_items = {f"k{i}": f"v{i}" for i in range(MAX_METADATA_ITEMS + 1)}
    with pytest.raises(ValidationError) as exc1:
        AgentConnectionCreate(
            connection_id="c1",
            display_name="C1",
            provider_or_runtime="p1",
            metadata=too_many_items,
        )
    assert "maximum allowed entries" in str(exc1.value)

    # Exceed key length
    with pytest.raises(ValidationError) as exc2:
        AgentConnectionCreate(
            connection_id="c1",
            display_name="C1",
            provider_or_runtime="p1",
            metadata={"k" * 65: "v"},
        )
    assert "exceeds maximum length" in str(exc2.value)

    # Exceed value length
    with pytest.raises(ValidationError) as exc3:
        AgentConnectionCreate(
            connection_id="c1",
            display_name="C1",
            provider_or_runtime="p1",
            metadata={"k": "v" * 513},
        )
    assert "exceeds maximum length" in str(exc3.value)


def test_top_level_secret_fields_rejected_by_extra_forbid(client: TestClient) -> None:
    res = client.post(
        "/api/v1/agent-connections",
        json={
            "connection_id": "bad-conn",
            "display_name": "Bad Conn",
            "provider_or_runtime": "p1",
            "api_key": "sk-12345",
        },
    )
    assert res.status_code == 422


# --- Bridge & Reserved Metadata Keys -----------------------------------------


def test_reserved_bridge_keys_rejected_in_user_metadata() -> None:
    for reserved_key in ["connection_id", "provider_or_runtime", "model_id", "connection_kind"]:
        with pytest.raises(ValidationError) as exc:
            AgentConnectionCreate(
                connection_id="c1",
                display_name="C1",
                provider_or_runtime="p1",
                metadata={reserved_key: "hack"},
            )
        assert "reserved internal bridge key" in str(exc.value)


def test_bridge_preserves_system_metadata_without_collision(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="conn-1",
            display_name="Conn 1",
            provider_or_runtime="openrouter",
            status=AgentConnectionStatus.CONNECTED,
        )
    )
    agent_repo.register(
        ConnectedAgentCreate(
            agent_id="agent-1",
            display_name="Agent 1",
            connection_id="conn-1",
            model_id="qwen/qwen-2.5-coder-32b-instruct",
            metadata={"env": "production", "team": "backend"},
        ),
        conn_repo,
    )

    bridge = ConnectedAgentCandidateBridge(conn_repo, agent_repo)
    descriptors = bridge.get_descriptors()

    desc = descriptors["agent-1"]
    assert desc.metadata["connection_id"] == "conn-1"
    assert desc.metadata["provider_or_runtime"] == "openrouter"
    assert desc.metadata["model_id"] == "qwen/qwen-2.5-coder-32b-instruct"
    assert desc.metadata["env"] == "production"
    assert desc.metadata["team"] == "backend"


# --- Referential Integrity & Concurrency -------------------------------------


def test_nonexistent_connection_reference_rejected(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
    with pytest.raises(ConnectionNotFoundError):
        agent_repo.register(
            ConnectedAgentCreate(
                agent_id="orphan-agent",
                display_name="Orphan Agent",
                connection_id="does-not-exist",
            ),
            conn_repo,
        )


def test_duplicate_connection_safe_typed_failure(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, _ = fresh_repos
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


def test_duplicate_agent_safe_typed_failure(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
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


def test_dependent_connection_deletion_safe(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
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


def test_concurrent_registration_and_deletion(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="shared-conn",
            display_name="Shared Conn",
            provider_or_runtime="p1",
        )
    )

    # 1. Concurrent Duplicate Connection Registration
    def _register_conn(idx: int) -> bool:
        try:
            conn_repo.register(
                AgentConnectionCreate(
                    connection_id="shared-conn",
                    display_name=f"Shared Conn {idx}",
                    provider_or_runtime="p1",
                )
            )
            return True
        except DuplicateConnectionError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_register_conn, range(10)))
    assert results.count(True) == 0  # All failed because shared-conn exists

    # 2. Concurrent Duplicate Agent Registration
    def _register_agent(idx: int) -> bool:
        try:
            agent_repo.register(
                ConnectedAgentCreate(
                    agent_id="shared-agent",
                    display_name=f"Agent {idx}",
                    connection_id="shared-conn",
                ),
                conn_repo,
            )
            return True
        except DuplicateAgentError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        agent_results = list(pool.map(_register_agent, range(10)))
    assert agent_results.count(True) == 1  # Exactly one registration succeeded

    # 3. Concurrent Delete Guard
    def _try_delete_conn(_: int) -> bool:
        try:
            return conn_repo.delete("shared-conn", agent_repo)
        except ConnectionHasDependentAgentsError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        delete_results = list(pool.map(_try_delete_conn, range(10)))
    assert delete_results.count(True) == 0  # Blocked due to shared-agent


# --- Mutation Leakage Prevention ---------------------------------------------


def test_frozen_domain_models_prevent_direct_attribute_mutation(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
    conn_repo.register(
        AgentConnectionCreate(
            connection_id="c1",
            display_name="C1 Original",
            provider_or_runtime="p1",
        )
    )
    retrieved = conn_repo.get("c1")
    assert retrieved is not None

    with pytest.raises(ValidationError):
        retrieved.display_name = "Hacked Name"  # Frozen assignment fails!

    assert conn_repo.get("c1").display_name == "C1 Original"


def test_repository_update_semantics(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos
    created = conn_repo.register(
        AgentConnectionCreate(
            connection_id="c1",
            display_name="C1 Original",
            provider_or_runtime="p1",
            status=AgentConnectionStatus.CONNECTED,
        )
    )
    t0 = created.created_at

    updated = conn_repo.update(
        "c1",
        AgentConnectionUpdate(
            display_name="C1 Updated",
            status=AgentConnectionStatus.DISABLED,
        ),
    )

    assert updated.display_name == "C1 Updated"
    assert updated.status == AgentConnectionStatus.DISABLED
    assert updated.created_at == t0
    assert updated.updated_at >= t0


# --- Router Bridge & Eligibility Tests ---------------------------------------


def test_router_bridge_and_eligibility(
    fresh_repos: tuple[AgentConnectionRepository, ConnectedAgentRepository],
) -> None:
    conn_repo, agent_repo = fresh_repos

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
    assert "disabled-agent" not in descriptors
    assert "unreachable-agent" not in descriptors

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

    task_match = TaskSpec(
        key="t1",
        name="impl",
        task_type="implementation",
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    req_match = build_routing_request(task_match, candidate_agent_types=["code-agent"])
    decision_match = router.route(req_match, candidates)
    assert decision_match.selected_agent_type == "code-agent"


# --- REST API Endpoints & Status Transitions ----------------------------------


def test_api_endpoints_round_trip_and_status_transitions(client: TestClient) -> None:
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

    # 2. Create Connected Agent
    res2 = client.post(
        "/api/v1/connected-agents",
        json={
            "agent_id": "my-qwen-agent",
            "display_name": "My Qwen Agent",
            "connection_id": "openrouter-personal",
            "model_id": "qwen/qwen-2.5-coder-32b-instruct",
            "capabilities": ["code_generation"],
        },
    )
    assert res2.status_code == 201

    # 3. PATCH Connection Status -> DISABLED
    res3 = client.patch(
        "/api/v1/agent-connections/openrouter-personal",
        json={"status": "disabled"},
    )
    assert res3.status_code == 200
    assert res3.json()["status"] == "disabled"

    # 4. PATCH Agent enabled state -> False
    res4 = client.patch(
        "/api/v1/connected-agents/my-qwen-agent",
        json={"enabled": False},
    )
    assert res4.status_code == 200
    assert res4.json()["enabled"] is False

    # 5. Typed Error Envelope 404 for Unknown Connection
    res5 = client.get("/api/v1/agent-connections/unknown-conn")
    assert res5.status_code == 404
    assert res5.json()["error"]["code"] == APIErrorCode.AGENT_CONNECTION_NOT_FOUND

    # 6. Typed Error Envelope 404 for Unknown Agent
    res6 = client.get("/api/v1/connected-agents/unknown-agent")
    assert res6.status_code == 404
    assert res6.json()["error"]["code"] == APIErrorCode.CONNECTED_AGENT_NOT_FOUND

    # 7. Typed Error Envelope 409 for Duplicate Connection
    res7 = client.post(
        "/api/v1/agent-connections",
        json={
            "connection_id": "openrouter-personal",
            "display_name": "OpenRouter Personal",
            "connection_kind": "api",
            "provider_or_runtime": "openrouter",
        },
    )
    assert res7.status_code == 409
    assert res7.json()["error"]["code"] == APIErrorCode.AGENT_CONNECTION_EXISTS
