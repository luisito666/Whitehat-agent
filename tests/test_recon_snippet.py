"""Tests de run_recon_snippet: gate scope.yaml + contencion real + ledger."""
import json

from pentest_agent.tools.pysnippet import run_recon_snippet


class TestReconSnippetGate:
    def test_target_fuera_de_scope_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_SCOPE_FILE", str(tmp_path / "no-scope.yaml"))
        monkeypatch.chdir(tmp_path)
        out = json.loads(run_recon_snippet.invoke(
            {"code": "print(1)", "host_target": "8.8.8.8"}))
        assert out["blocked"] is True
        assert "FUERA DE SCOPE" in out["reason"]

    def test_no_exige_engagement_ni_aprobacion(self, tmp_path, monkeypatch):
        """A diferencia de la variante exploit, recon solo exige scope.yaml."""
        monkeypatch.setenv("PENTEST_SCOPE_FILE", str(tmp_path / "no-scope.yaml"))
        monkeypatch.delenv("PENTEST_ENGAGEMENT_FILE", raising=False)
        monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
        monkeypatch.chdir(tmp_path)
        out = json.loads(run_recon_snippet.invoke(
            {"code": "print('libre')", "host_target": "127.0.0.1"}))
        assert out["completed"] is True
        assert "libre" in out["stdout"]


class TestReconSnippetRun:
    def test_snippet_simple_corre_y_ledger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_SCOPE_FILE", str(tmp_path / "no-scope.yaml"))
        monkeypatch.chdir(tmp_path)
        out = json.loads(run_recon_snippet.invoke(
            {"code": "print('hola'); print(sorted([3,1,2]))", "host_target": "127.0.0.1"}))
        assert out["completed"] is True
        assert out["exit_code"] == 0
        assert "hola" in out["stdout"] and "[1, 2, 3]" in out["stdout"]
        assert out["code_sha256"]
        ledger = tmp_path / "reports" / "evidence.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().strip().splitlines()[-1])
        assert rec["technique"] == "recon-python-snippet"
        assert rec["code_sha256"] == out["code_sha256"]
        assert "engagement_id" not in rec  # no-ofensivo: sin engagement

    def test_connect_fuera_del_scope_bloqueado_por_audit_hook(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_SCOPE_FILE", str(tmp_path / "no-scope.yaml"))
        monkeypatch.chdir(tmp_path)
        code = ("import socket\n"
                "socket.create_connection(('8.8.8.8', 53), timeout=3)\n")
        out = json.loads(run_recon_snippet.invoke(
            {"code": code, "host_target": "127.0.0.1"}))
        assert out["completed"] is False
        assert "FUERA DE SCOPE" in out["stderr"]

    def test_subproceso_bloqueado(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_SCOPE_FILE", str(tmp_path / "no-scope.yaml"))
        monkeypatch.chdir(tmp_path)
        code = ("import subprocess\n"
                "subprocess.run(['true'])\n")
        out = json.loads(run_recon_snippet.invoke(
            {"code": code, "host_target": "127.0.0.1"}))
        assert out["completed"] is False
        assert "subprocesos" in out["stderr"]
