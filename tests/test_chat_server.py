"""Tests del sidecar de chat (FastAPI, solo 127.0.0.1:9000).

Task 1: GET /status con workers stubbeados (httpx.MockTransport).
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from pentest_agent import chat_server


@pytest.fixture
def client() -> TestClient:
    return TestClient(chat_server.app)


def _mock_cards(up_roles: set[str]):
    """MockTransport que responde 200 a la agent card de los roles `up`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent.json":
            role_up = any(
                f":{port}/" in str(request.url) or str(request.url).endswith(f":{port}")
                for role, port in chat_server.WORKER_PORTS.items()
                if role in up_roles
            )
            if role_up:
                return httpx.Response(200, json={"name": "worker"})
        return httpx.Response(503)

    return handler


def test_bind_is_loopback_only():
    assert chat_server.HOST == "127.0.0.1"
    assert chat_server.PORT == 9000


def test_status_ok(client, monkeypatch):
    monkeypatch.setattr(
        chat_server,
        "_new_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_mock_cards({"recon", "vuln", "reporter"}))),
    )
    monkeypatch.delenv("A2A_EXPLOIT_URL", raising=False)

    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["protocol"] == 1
    assert body["stack"] == "up"
    roles = {w["role"]: w for w in body["workers"]}
    assert set(roles) == {"recon", "vuln", "reporter"}
    assert all(w["up"] for w in body["workers"])
    assert all(w["url"].startswith("http://127.0.0.1:") for w in body["workers"])
    # sin engagement.yaml en el worktree -> resumen vacio, nunca 500
    assert body["engagement"] == {
        "id": None,
        "client": None,
        "valid": False,
        "approved": False,
    }


def test_status_soft_fails_when_workers_down(client, monkeypatch):
    monkeypatch.setattr(
        chat_server,
        "_new_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_mock_cards(set()))),
    )
    monkeypatch.delenv("A2A_EXPLOIT_URL", raising=False)

    body = client.get("/status").json()
    assert body["stack"] == "down"
    assert all(w["up"] is False for w in body["workers"])


def test_status_includes_exploit_when_env_set(client, monkeypatch):
    monkeypatch.setenv("A2A_EXPLOIT_URL", "http://127.0.0.1:9104")
    monkeypatch.setattr(
        chat_server,
        "_new_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_mock_cards(set()))),
    )
    roles = {w["role"] for w in client.get("/status").json()["workers"]}
    assert roles == {"recon", "vuln", "reporter", "exploit"}
