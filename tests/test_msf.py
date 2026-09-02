"""Tests del gate Metasploit: allowlist de modulos + fail-closed."""
import json
from datetime import date, timedelta

import pytest

from pentest_agent.engagement import EngagementError
from pentest_agent.tools.msf import (
    ModuleNotAllowedError,
    run_metasploit_module,
    run_msf_module,
)


def _engagement(tmp_path, modules=None):
    data = {
        "engagement_id": "ENG-MSF-001",
        "client": {"name": "Test", "contact": "t"},
        "authorization": {
            "reference": "roe-msf-001",
            "valid_from": str(date.today() - timedelta(days=1)),
            "valid_until": str(date.today() + timedelta(days=30)),
        },
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {
            "allowed_techniques": ["metasploit-module", "path-traversal-poc"],
            "prohibited": ["persistence", "dos", "data-exfiltration"],
        },
        "msf": {"allowed_modules": modules if modules is not None else [
            "exploit/multi/http/wp_plugin_upload"
        ]},
    }
    import yaml
    p = tmp_path / "engagement.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


class TestMsfGate:
    def test_sin_engagement_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(tmp_path / "nope.yaml"))
        out = json.loads(run_metasploit_module.invoke({
            "host_target": "127.0.0.1", "module": "exploit/unix/ftp/vsftpd_234_backdoor"}))
        assert out["blocked"] is True

    def test_modulo_fuera_de_allowlist_bloquea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_engagement(tmp_path)))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-MSF-001")
        monkeypatch.setenv("MSF_BACKEND", "sim")
        out = json.loads(run_metasploit_module.invoke({
            "host_target": "127.0.0.1", "module": "exploit/unix/ftp/vsftpd_234_backdoor"}))
        assert out["blocked"] is True
        assert "NO autorizado" in out["reason"]

    def test_modulo_en_allowlist_con_aprobacion_corre_sim(self, tmp_path, monkeypatch):
        p = _engagement(tmp_path, modules=["exploit/unix/ftp/vsftpd_234_backdoor"])
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(p))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-MSF-001")
        monkeypatch.setenv("MSF_BACKEND", "sim")
        monkeypatch.chdir(tmp_path)
        rec = run_msf_module("127.0.0.1", "exploit/unix/ftp/vsftpd_234_backdoor",
                             {"RHOSTS": "127.0.0.1"})
        assert rec["msf"]["backend"] == "sim"
        assert rec["engagement_id"] == "ENG-MSF-001"
        # ledger escrito
        lines = (tmp_path / "reports" / "evidence.jsonl").read_text().splitlines()
        assert json.loads(lines[-1])["exploit_method"] == "metasploit"

    def test_tecnica_prohibida_gana(self, tmp_path, monkeypatch):
        import yaml
        p = _engagement(tmp_path, modules=["exploit/x/y"])
        data = yaml.safe_load(p.read_text())
        data["rules_of_engagement"]["prohibited"].append("metasploit-module")
        p.write_text(yaml.safe_dump(data))
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(p))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-MSF-001")
        out = json.loads(run_metasploit_module.invoke({
            "host_target": "127.0.0.1", "module": "exploit/x/y"}))
        assert out["blocked"] is True
        assert "PROHIBIDA" in out["reason"]

    def test_sin_aprobacion_bloquea(self, tmp_path, monkeypatch):
        p = _engagement(tmp_path, modules=["exploit/x/y"])
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(p))
        monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
        out = json.loads(run_metasploit_module.invoke({
            "host_target": "127.0.0.1", "module": "exploit/x/y"}))
        assert out["blocked"] is True
        assert "APROBACION" in out["reason"]
