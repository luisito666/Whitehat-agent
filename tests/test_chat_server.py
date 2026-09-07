"""Tests del sidecar de chat (FastAPI, solo 127.0.0.1:9000).

Task 1: GET /status con workers stubbeados (httpx.MockTransport).
Task 2: POST /chat single-turn con el supervisor monkeypatcheado a un stub
        cuyo astream_events emite 2 chunks + done.
Task 3: GET /chat/{sid}/events -> SSE (text/event-stream) con replay por cursor.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

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


# --------------------------------------------------------------------- Task 3
def _parse_sse(raw: str) -> list[dict]:
    """text/event-stream -> lista de {id, event, data}."""
    events: list[dict] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        rec: dict = {}
        for line in block.splitlines():
            field, _, value = line.partition(": ")
            if field == "id":
                rec["id"] = int(value)
            elif field == "event":
                rec["event"] = value
            elif field == "data":
                rec["data"] = json.loads(value)
        events.append(rec)
    return events


def _read_sse(client, url: str, **kwargs) -> tuple[httpx.Response, list[dict]]:
    with client.stream("GET", url, **kwargs) as resp:
        raw = "".join(resp.iter_text())
        return resp, _parse_sse(raw)


def test_sse_streams_events(client, monkeypatch):
    monkeypatch.setattr(a2a_team, "build_a2a_supervisor", lambda *a, **k: _StubAgent())
    sid = client.post("/chat", json={"message": "hola equipo"}).json()["session_id"]

    resp, events = _read_sse(client, f"/chat/{sid}/events")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [e["event"] for e in events] == ["chat.delta", "chat.delta", "chat.done"]
    assert [e["id"] for e in events] == [1, 2, 3]
    assert events[-1]["event"] == "chat.done"
    assert "".join(e["data"]["text"] for e in events if e["event"] == "chat.delta") == "Hola operador"


def test_sse_cursor_replay(client, monkeypatch):
    monkeypatch.setattr(a2a_team, "build_a2a_supervisor", lambda *a, **k: _StubAgent())
    sid = client.post("/chat", json={"message": "hola equipo"}).json()["session_id"]
    all_events = chat_server.get_events(sid)
    first_id = all_events[0]["id"]

    _, events = _read_sse(client, f"/chat/{sid}/events", params={"cursor": first_id})

    assert [e["id"] for e in events] == [e["id"] for e in all_events if e["id"] > first_id]
    assert first_id not in [e["id"] for e in events]

    # mismo comportamiento via header Last-Event-ID
    _, hdr_events = _read_sse(
        client, f"/chat/{sid}/events", headers={"Last-Event-ID": str(first_id)}
    )
    assert [e["id"] for e in hdr_events] == [e["id"] for e in events]


def test_sse_unknown_session_404(client):
    resp = client.get("/chat/does-not-exist/events")
    assert resp.status_code == 404


# --------------------------------------------------------------------- Task 4
_ENGAGEMENT_YAML = """\
engagement_id: ENG-TEST-2026-777
client:
  name: "ACME Test Corp"
  contact: "Alguien"
authorization:
  reference: "roE-test-ref-v9"
  valid_from: "2026-01-01"
  valid_until: "2026-12-31"
scope:
  allowed_targets:
    - "10.11.12.13/32"
rules_of_engagement:
  allowed_techniques:
    - "path-traversal-poc"
  prohibited:
    - "dos"
  max_evidence_items: 5
msf:
  allowed_modules:
    - "exploit/unix/ftp/vsftpd_234_backdoor"
"""


@pytest.fixture
def engagement_file(tmp_path, monkeypatch):
    p = tmp_path / "engagement.yaml"
    p.write_text(_ENGAGEMENT_YAML)
    monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(p))
    return p


def test_engagement_summary_sin_secretos(client, engagement_file, monkeypatch):
    monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)

    resp = client.get("/engagement")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body) == {"id", "client", "valid", "approved", "window", "auth_reference"}
    assert body["id"] == "ENG-TEST-2026-777"
    assert body["client"] == "ACME Test Corp"
    assert body["valid"] is True
    assert body["approved"] is False
    assert body["window"] == {"valid_from": "2026-01-01", "valid_until": "2026-12-31"}
    assert body["auth_reference"] == "roE-test-ref-v9"

    # NINGUN valor filtra scope crudo, allowlist de modulos ni rutas de archivo
    blob = json.dumps(body)
    assert "10.11.12.13" not in blob
    assert "allowed_targets" not in blob
    assert "allowed_modules" not in blob
    assert "vsftpd_234_backdoor" not in blob
    assert "path-traversal-poc" not in blob
    assert str(engagement_file) not in blob
    assert "engagement.yaml" not in blob


def test_engagement_approved_reflects_env(client, engagement_file, monkeypatch):
    monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-TEST-2026-777")
    assert client.get("/engagement").json()["approved"] is True


def test_engagement_not_found_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(tmp_path / "no-engagement.yaml"))
    resp = client.get("/engagement")
    assert resp.status_code == 404


def test_approve_always_501(client, engagement_file):
    resp = client.post("/engagement/approve")
    assert resp.status_code == 501
    assert resp.json() == {"error": "approval is in-person only via approve.py"}

    # tambien 501 con body y sin importar el engagement vigente
    resp2 = client.post("/engagement/approve", json={"engagement_id": "ENG-TEST-2026-777"})
    assert resp2.status_code == 501
    assert resp2.json() == {"error": "approval is in-person only via approve.py"}


def test_ledger_tail(client, tmp_path, monkeypatch):
    ledger = tmp_path / "evidence.jsonl"
    rows = [json.dumps({"n": i, "ts": f"2026-09-07T0{i}:00:00+00:00"}) for i in range(5)]
    ledger.write_text("\n".join(rows) + "\n")
    monkeypatch.setattr(chat_server, "LEDGER_PATH", ledger)

    body = client.get("/ledger", params={"tail": 3}).json()
    assert [e["n"] for e in body["entries"]] == [2, 3, 4]
    assert body["total"] == 3

    body_all = client.get("/ledger", params={"tail": 0}).json()
    assert [e["n"] for e in body_all["entries"]] == [0, 1, 2, 3, 4]

    # una linea corrupta se omite, el endpoint no se rompe
    ledger.write_text("\n".join(rows) + "\nno-es-json{\n")
    body_corrupt = client.get("/ledger", params={"tail": 0}).json()
    assert [e["n"] for e in body_corrupt["entries"]] == [0, 1, 2, 3, 4]

    # archivo ausente -> vacio
    monkeypatch.setattr(chat_server, "LEDGER_PATH", tmp_path / "no-such-file.jsonl")
    assert client.get("/ledger").json() == {"entries": [], "total": 0}


def test_ledger_tail_capped_at_100(client, tmp_path, monkeypatch):
    ledger = tmp_path / "evidence.jsonl"
    ledger.write_text("\n".join(json.dumps({"n": i}) for i in range(250)) + "\n")
    monkeypatch.setattr(chat_server, "LEDGER_PATH", ledger)

    body = client.get("/ledger", params={"tail": 999}).json()
    assert len(body["entries"]) == 100
    assert body["entries"][0]["n"] == 150
    assert body["entries"][-1]["n"] == 249


# --------------------------------------------------------------------- Task 5
class _HandoffAgent:
    """Supervisor falso: emite un chunk, delega a un worker A2A y cierra.

    Reproduce el patron de eventos que LangGraph produce para un handoff en
    build_a2a_supervisor: on_chain_start/on_chain_end del nodo cuyo `name` es
    el rol del worker (recon/vuln/reporter/exploit), con el AIMessage de
    delegacion (additional_kwargs['task']) como ultimo mensaje del estado.
    """

    def __init__(self, role: str = "recon", task: str = "scan 10.0.0.1"):
        self.role = role
        self.task = task

    async def astream_events(self, inputs, config=None, version=None, **kw):
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": AIMessageChunk(content="Delegando... ")},
        }
        delegate = AIMessage(
            content=f"Delegando a {self.role}: {self.task}",
            additional_kwargs={"delegate": self.role, "task": self.task},
        )
        yield {
            "event": "on_chain_start",
            "name": self.role,
            "data": {"input": {"messages": [delegate]}},
        }
        yield {
            "event": "on_chain_end",
            "name": self.role,
            "data": {"output": {"messages": [AIMessage(content=f"[{self.role}] ok")]}},
        }
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {}}


def test_worker_activity_surfaced(client, monkeypatch):
    monkeypatch.setattr(
        a2a_team,
        "build_a2a_supervisor",
        lambda *a, **k: _HandoffAgent(role="recon", task="scan 10.0.0.1"),
    )

    sid = client.post("/chat", json={"message": "audita 10.0.0.1"}).json()["session_id"]
    events = chat_server.get_events(sid)

    activity = [e["data"] for e in events if e["event"] == "agent.activity"]
    assert [a["action"] for a in activity] == ["handoff", "done"]
    assert all(a["role"] == "recon" for a in activity)
    assert activity[0]["detail"] == "scan 10.0.0.1"

    # el turno cierra normal y los deltas de texto siguen fluyendo
    assert events[-1]["event"] == "chat.done"
    assert any(e["event"] == "chat.delta" for e in events)


def test_worker_activity_correlation_failure_is_soft(client, monkeypatch):
    monkeypatch.setattr(
        a2a_team, "build_a2a_supervisor", lambda *a, **k: _HandoffAgent(role="vuln")
    )

    def _boom(*a, **k):
        raise RuntimeError("correlation exploded")

    monkeypatch.setattr(chat_server, "_handoff_detail", _boom)

    sid = client.post("/chat", json={"message": "hola"}).json()["session_id"]
    events = chat_server.get_events(sid)

    # la correlacion reventada solo pierde el evento extra: el turno completa
    assert events[-1]["event"] == "chat.done"
    assert not any(e["event"] == "error" for e in events)


# --------------------------------------------------------------------- Task 6
# E2E: el sidecar COMO PROCESO REAL (subprocess) en modo determinista, sin LLM
# ni red. Ejercita /status -> POST /chat -> SSE completo hasta chat.done.

def _free_port(preferred: int = 9000) -> int:
    """Puerto libre en loopback: intenta `preferred`, si no, uno efimero."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free TCP port on 127.0.0.1")


@pytest.fixture
def sidecar_url(tmp_path):
    """Lanza `python -m pentest_agent.chat_server` como proceso real en modo
    determinista (PENTEST_CHAT_DETERMINISTIC=1) sobre un puerto libre y espera
    readiness polleando GET /status (timeout 30s). El proceso SIEMPRE se mata en
    teardown; si arranca mal, se imprime su stdout/stderr para debugging."""
    port = _free_port(9000)
    env = os.environ.copy()
    env["PENTEST_CHAT_DETERMINISTIC"] = "1"
    env["PENTEST_CHAT_HOST"] = "127.0.0.1"
    env["PENTEST_CHAT_PORT"] = str(port)
    # el proceso hijo no debe ver ningun engagement.yaml del entorno
    env["PENTEST_ENGAGEMENT_FILE"] = str(tmp_path / "no-engagement.yaml")
    env.pop("A2A_EXPLOIT_URL", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "pentest_agent.chat_server"],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"

    def _dump_and_fail(reason: str) -> None:
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        pytest.fail(
            f"{reason}\nrc={proc.returncode}\n"
            f"--- sidecar stdout ---\n{out}\n--- sidecar stderr ---\n{err}"
        )

    try:
        deadline = time.monotonic() + 30.0
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _dump_and_fail("sidecar exited before becoming ready")
            try:
                resp = httpx.get(f"{base}/status", timeout=5.0)
                if resp.status_code == 200:
                    break
                last_err = RuntimeError(f"/status -> {resp.status_code}")
            except httpx.HTTPError as exc:
                last_err = exc
            time.sleep(0.3)
        else:
            _dump_and_fail(f"sidecar not ready after 30s (last error: {last_err!r})")
        yield base
    finally:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.wait()


def test_e2e_deterministic_status_chat_sse(sidecar_url):
    base = sidecar_url

    # /status -> 200, protocolo 1
    st = httpx.get(f"{base}/status", timeout=10.0)
    assert st.status_code == 200
    assert st.json()["protocol"] == 1

    # POST /chat {"message":"ping"} -> 200 con session_id
    resp = httpx.post(f"{base}/chat", json={"message": "ping"}, timeout=30.0)
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    assert session_id

    # GET /chat/{sid}/events -> stream completo hasta chat.done; el eco
    # determinista responde "pong"
    with httpx.stream("GET", f"{base}/chat/{session_id}/events", timeout=30.0) as stream:
        raw = "".join(stream.iter_text())
    events = _parse_sse(raw)

    assert events, raw
    assert events[-1]["event"] == "chat.done"
    final_text = "".join(
        e["data"].get("text", "") for e in events if e["event"] == "chat.delta"
    )
    assert "pong" in final_text
