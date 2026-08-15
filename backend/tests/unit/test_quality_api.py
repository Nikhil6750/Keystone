"""Unit tests for Stage 9D Software Quality Factory REST API Endpoints."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.contracts.quality import (
    QualityEvidence,
    QualityGateResult,
    QualityGateStatus,
    QualityGateType,
    QualityRun,
    QualityVerdict,
)
from app.engine.quality.repository import InMemoryQualityRepository
from app.main import app


@pytest.fixture
def client_with_quality_repo() -> tuple[TestClient, InMemoryQualityRepository]:
    repo = InMemoryQualityRepository()
    app.state.quality_repository = repo
    client = TestClient(app)
    return client, repo


def test_quality_profile_endpoints(
    client_with_quality_repo: tuple[TestClient, InMemoryQualityRepository],
) -> None:
    client, repo = client_with_quality_repo

    # 1. Create Profile
    payload = {
        "profile_id": "api-test-profile",
        "name": "API Test Profile",
        "description": "Profile created via API",
        "target_languages": ["python"],
        "target_frameworks": ["fastapi"],
        "gates": [
            {
                "gate_id": "api-gate-1",
                "gate_type": "test",
                "name": "API Gate",
                "required": True,
                "timeout_seconds": 30.0,
                "applicable_scope": "workspace",
                "configuration": {},
                "order": 10,
            }
        ],
        "is_default": True,
        "metadata": {},
    }

    res_post = client.post("/api/v1/quality/profiles", json=payload)
    assert res_post.status_code == 201
    assert res_post.json()["profile_id"] == "api-test-profile"

    # 2. Get Profile
    res_get = client.get("/api/v1/quality/profiles/api-test-profile")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "API Test Profile"

    # 3. List Profiles
    res_list = client.get("/api/v1/quality/profiles")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1


def test_quality_run_inspection_endpoints(
    client_with_quality_repo: tuple[TestClient, InMemoryQualityRepository],
) -> None:
    client, repo = client_with_quality_repo

    # Populate a sample run
    gr1 = QualityGateResult(
        gate_id="g-test",
        gate_type=QualityGateType.TEST,
        name="Unit Tests",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="All passed", exit_code=0),
    )
    v = QualityVerdict.compute([gr1], verdict_id="verdict-101")
    now = datetime.now(UTC)
    qrun = QualityRun(
        run_id="qrun-101",
        execution_id="exec-101",
        workflow_id="wf-101",
        task_id="task-101",
        attempt_number=1,
        agent_id="agent-py",
        gate_results=(gr1,),
        verdict=v,
        created_at=now,
        completed_at=now,
    )
    repo.save_run(qrun)

    # 1. Get Quality Run
    res_run = client.get("/api/v1/quality/runs/qrun-101")
    assert res_run.status_code == 200
    data = res_run.json()
    assert data["run_id"] == "qrun-101"
    assert data["passed"] is True
    assert data["status"] == "ACCEPTED"

    # 2. Get Run Gates
    res_gates = client.get("/api/v1/quality/runs/qrun-101/gates")
    assert res_gates.status_code == 200
    gates_data = res_gates.json()
    assert len(gates_data) == 1
    assert gates_data[0]["gate_id"] == "g-test"

    # 3. Get Verdict
    res_verdict = client.get("/api/v1/quality/runs/qrun-101/verdict")
    assert res_verdict.status_code == 200
    assert res_verdict.json()["passed"] is True

    # 4. History queries
    res_hist = client.get("/api/v1/quality/history?execution_id=exec-101")
    assert res_hist.status_code == 200
    assert len(res_hist.json()) == 1
    assert res_hist.json()[0]["run_id"] == "qrun-101"
