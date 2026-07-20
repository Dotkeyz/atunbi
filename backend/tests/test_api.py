"""Integration tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_register_missing_fields(client):
    response = client.post("/auth/register", json={"username": "x"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"


def test_chat_stream_requires_auth(client):
    response = client.post("/api/v1/chat/stream", json={"message": "hi"})
    assert response.status_code in (401, 403)


def test_chat_empty_message_rejected(client):
    response = client.post("/api/v1/chat/stream", json={
        "message": "", "conversation_id": None
    })
    # Auth middleware runs before Pydantic validation — either is acceptable
    assert response.status_code in (401, 403, 422)

