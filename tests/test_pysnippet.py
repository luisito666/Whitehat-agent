"""Tests de run_python_snippet: gate fail-closed + contencion real."""
import json
from datetime import date, timedelta

import pytest

from pentest_agent.engagement import EngagementError  # noqa: F401
from pentest_agent.tools.pysnippet import run_python_snippet


def _engagement(tmp_path, techniques=None):
    data = {
        "engagement_id": "ENG-PY-001",
        "client": {"name": "Test", "contact": "t"},
        "authorization": {
            "reference": "roe-py-001",
            "valid_from": str(date.today() - timedelta(days=1)),
            "valid_until": str(date.today() + timedelta(days=30)),
        },
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {
            "allowed_techniques": techniques if techniques is not None
            else ["python-snippet"],
            "prohibited": ["persistence", "dos", "data-exfiltration"],
        },
    }
    import yaml
    p = tmp_path / "engagement.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


class TestPySnippetGate:
    def test_sin_engagement_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(tmp_path / "nope.yaml"))
        out = json.loads(run_python_snippet.invoke(
            {"code": "print(1)", "host_target": "127.0.0.1"}))
        assert out["blocked"] is True

    def test_tecnica_no_autorizada_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE",
                           str(_engagement(tmp_path, techniques=["path-traversal-poc"])))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-PY-001")
        out = json.loads(run_python_snippet.invoke(
            {"code": "print(1)", "host_target": "127.0.0.1"}))
        assert out["blocked"] is True

    def test_sin_aprobacion_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
        out = json.loads(run_python_snippet.invoke(
            {"code": "print(1)", "host_target": "127.0.0.1"}))
        assert out["blocked"] is True


class TestPySnippetRun:
    def test_snippet_simple_corre_y_ledger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-PY-001")
        monkeypatch.chdir(tmp_path)
        out = json.loads(run_python_snippet.invoke(
            {"code": "print('hola'); print(6*7)", "host_target": "127.0.0.1"}))
        assert out["completed"] is True
        assert out["exit_code"] == 0
        assert "hola" in out["stdout"] and "42" in out["stdout"]
        assert out["code_sha256"]
        ledger = tmp_path / "reports" / "evidence.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().strip().splitlines()[-1])
        assert rec["technique"] == "python-snippet"
        assert rec["code_sha256"] == out["code_sha256"]

    def test_connect_fuera_de_scope_bloqueado_por_audit_hook(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-PY-001")
        monkeypatch.chdir(tmp_path)
        code = ("import socket\n"
                "socket.create_connection(('8.8.8.8', 53), timeout=3)\n")
        out = json.loads(run_python_snippet.invoke(
            {"code": code, "host_target": "127.0.0.1"}))
        assert out["completed"] is False
        assert "FUERA DE SCOPE" in out["stderr"]

    def test_subproceso_bloqueado(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-PY-001")
        monkeypatch.chdir(tmp_path)
        code = ("import subprocess\n"
                "subprocess.run(['true'])\n")
        out = json.loads(run_python_snippet.invoke(
            {"code": code, "host_target": "127.0.0.1"}))
        assert out["completed"] is False
        assert "subprocesos" in out["stderr"]

    def test_connect_dentro_de_scope_intenta(self, tmp_path, monkeypatch):
        """A 127.0.0.1 (en scope) SÍ se le permite intentar conectar."""
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-PY-001")
        monkeypatch.chdir(tmp_path)
        code = ("import socket\n"
                "try:\n"
                "    socket.create_connection(('127.0.0.1', 1), timeout=2)\n"
                "except ConnectionError:\n"
                "    print('refused-ok')\n")
        out = json.loads(run_python_snippet.invoke(
            {"code": code, "host_target": "127.0.0.1"}))
        assert out["completed"] is True
        assert "refused-ok" in out["stdout"]
