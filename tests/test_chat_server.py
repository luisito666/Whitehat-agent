"""Tests del sidecar de chat (FastAPI, solo 127.0.0.1:9000).

Task 1: GET /status con workers stubbeados (httpx.MockTransport).
Task 2: POST /chat single-turn con el supervisor monkeypatcheado a un stub
        cuyo astream_events emite 2 chunks + done.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from pentest_agent import a2a_team, chat_server


@pytest.fixture(autouse=True)
def _clean_state():
    """Cada test arranca con buffers vacios y el supervisor sin cachear."""
    chat_server._buffers.clear()
    chat_server._supervisor.cache_clear()
    yield
    chat_server._buffers.clear()
    chat_server._supervisor.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(chat_server.app)


# --------------------------------------------------------------------- Task 1
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


# --------------------------------------------------------------------- Task 2
class _StubAgent:
    """Supervisor falso: astream_events emite 2 chunks de texto + fin."""

    def __init__(self):
        self.configs: list[dict] = []

    async def astream_events(self, inputs, config=None, version=None, **kw):
        self.configs.append(config or {})
        for piece in ("Hola ", "operador"):
            yield {
                "event": "on_chat_model_stream",
                "name": "ChatOpenAI",
                "data": {"chunk": AIMessageChunk(content=piece)},
            }
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {}}


def test_chat_single_turn(client, monkeypatch):
    stub = _StubAgent()
    monkeypatch.setattr(a2a_team, "build_a2a_supervisor", lambda *a, **k: stub)

    resp = client.post("/chat", json={"message": "hola equipo"})
    assert resp.status_code == 200
    body = resp.json()

    session_id = body["session_id"]
    assert session_id
    assert body["cursor"] == "0"

    events = chat_server.get_events(session_id)
    assert [e["event"] for e in events] == ["chat.delta", "chat.delta", "chat.done"]
    assert [e["id"] for e in events] == [1, 2, 3]
    assert "".join(e["data"]["text"] for e in events if e["event"] == "chat.delta") == "Hola operador"

    # thread_id == session_id -> memoria de conversacion multi-turno
    assert stub.configs[0]["configurable"]["thread_id"] == session_id


def test_chat_reuses_supplied_session_id(client, monkeypatch):
    monkeypatch.setattr(a2a_team, "build_a2a_supervisor", lambda *a, **k: _StubAgent())

    body = client.post("/chat", json={"session_id": "sess-42", "message": "hey"}).json()
    assert body["session_id"] == "sess-42"
    assert [e["event"] for e in chat_server.get_events("sess-42")] == [
        "chat.delta",
        "chat.delta",
        "chat.done",
    ]


def test_chat_single_supervisor_build(client, monkeypatch):
    """El grafo se construye una sola vez (lru_cache) aunque haya varios turnos."""
    calls = {"n": 0}

    def _factory(*a, **k):
        calls["n"] += 1
        return _StubAgent()

    monkeypatch.setattr(a2a_team, "build_a2a_supervisor", _factory)
    client.post("/chat", json={"session_id": "s1", "message": "uno"})
    client.post("/chat", json={"session_id": "s1", "message": "dos"})
    assert calls["n"] == 1
