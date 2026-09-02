"""Tests del gate de explotacion: fail-closed en cada puerta."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from pentest_agent.engagement import Engagement, EngagementError, load_engagement
from pentest_agent.tools.exploit import append_evidence, prove_path_traversal


def _write_engagement(tmp_path, **over) -> Path:
    """Engagement valido por defecto; los tests sobreescriben campos."""
    from datetime import date
    data = {
        "engagement_id": "ENG-TEST-001",
        "client": {"name": "Test Client", "contact": "tester"},
        "authorization": {
            "reference": "roe-signed-001",
            "valid_from": str(date.today() - timedelta(days=1)),
            "valid_until": str(date.today() + timedelta(days=30)),
        },
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {
            "allowed_techniques": ["path-traversal-poc"],
            "prohibited": ["persistence", "dos", "data-exfiltration"],
        },
    }
    data.update(over)
    p = tmp_path / "engagement.yaml"
    p.write_text(yaml_dump(data))
    return p


def yaml_dump(data):
    import yaml
    return yaml.safe_dump(data)


class TestEngagementGate:
    def test_engagement_valido_pasa(self, tmp_path):
        eng = load_engagement(_write_engagement(tmp_path))
        eng.assert_valid()

    def test_sin_archivo_falla_cerrado(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(tmp_path / "nope.yaml"))
        with pytest.raises(EngagementError, match="sin engagement"):
            load_engagement()

    def test_expirado_falla(self, tmp_path):
        p = _write_engagement(
            tmp_path,
            authorization={"reference": "r", "valid_from": "2020-01-01",
                            "valid_until": "2020-12-31"},
        )
        with pytest.raises(EngagementError, match="EXPIRADO"):
            load_engagement(p).assert_valid()

    def test_tecnica_no_autorizada(self, tmp_path):
        eng = load_engagement(_write_engagement(tmp_path))
        with pytest.raises(EngagementError, match="no autorizada"):
            eng.assert_authorized("127.0.0.1", "rce-payload")

    def test_prohibida_gana_sobre_autorizada(self, tmp_path):
        data_over = {
            "rules_of_engagement": {
                "allowed_techniques": ["x", "path-traversal-poc"],
                "prohibited": ["path-traversal-poc"],
            }
        }
        p = _write_engagement(tmp_path, **data_over)
        eng = load_engagement(p)
        with pytest.raises(EngagementError, match="PROHIBIDA"):
            eng.assert_authorized("127.0.0.1", "path-traversal-poc")

    def test_target_fuera_de_scope(self, tmp_path):
        eng = load_engagement(_write_engagement(tmp_path))
        with pytest.raises(EngagementError, match="fuera del scope"):
            eng.assert_authorized("8.8.8.8", "path-traversal-poc")

    def test_sin_aprobacion_humana(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
        eng = load_engagement(_write_engagement(tmp_path))
        with pytest.raises(EngagementError, match="APROBACION"):
            eng.require_operator_approval()

    def test_aprobacion_correcta_pasa(self, tmp_path, monkeypatch):
        p = _write_engagement(tmp_path)
        eng = load_engagement(p)
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-TEST-001")
        eng.require_operator_approval()


class TestExplotacionIntegrada:
    def test_puertas_cerradas_no_toca_red(self, tmp_path, monkeypatch):
        """Sin engagement => prove_vulnerability ni siquiera abre socket."""
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(tmp_path / "nope.yaml"))
        monkeypatch.delenv("PENTEST_EXPLOIT_APPROVED", raising=False)
        from pentest_agent.tools.exploit import prove_vulnerability
        out = json.loads(prove_vulnerability.invoke({"base_url": "http://127.0.0.1:1", "host_target": "127.0.0.1"}))
        assert out["blocked"] is True

    def test_explotacion_completa_contra_lab(self, tmp_path, monkeypatch):
        """E2E: engagement + aprobacion + lab vulnerable => proven=true en ledger."""
        from pentest_agent.lab import build_lab

        srv, _web, _canary, token = build_lab(tmp_path / "lab")
        import threading
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        port = srv.server_address[1]

        p = _write_engagement(tmp_path)
        monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(p))
        monkeypatch.setenv("PENTEST_EXPLOIT_APPROVED", "ENG-TEST-001")
        monkeypatch.chdir(tmp_path)  # ledger en tmp

        rec = prove_path_traversal(f"http://127.0.0.1:{port}", "127.0.0.1")
        assert rec["proven"] is True
        assert token in rec["evidence_snippet"]
        # ledger append-only con el registro
        ledger = tmp_path / "reports" / "evidence.jsonl"
        assert ledger.exists()
        lines = ledger.read_text().strip().splitlines()
        assert json.loads(lines[-1])["proven"] is True
        srv.shutdown()
