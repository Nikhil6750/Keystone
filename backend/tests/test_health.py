"""Tests for the root and health endpoints."""

from httpx import AsyncClient


async def test_read_root(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "keystone-backend"
    assert body["version"] == "0.1.0"


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "keystone-backend",
        "version": "0.1.0",
    }
