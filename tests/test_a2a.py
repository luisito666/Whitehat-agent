"""Tests A2A: card, construccion de server y round-trip contra vuln (mock LLM)."""
import json

import pytest

from pentest_agent.a2a_server import ROLES, build_server


class TestRoles:
    def test_tres_roles_con_puertos_distintos(self):
        ports = [ROLES[r]["port"] for r in ROLES]
        assert sorted(ports) == [9101, 9102, 9103]


class TestServerBuild:
    def test_build_server_construye_app_por_rol(self):
        for role in ROLES:
            app = build_server(role)
            assert app is not None

    def test_agent_card_expone_skill_y_url(self):
        app = build_server("vuln", host="127.0.0.1", port=9102)
        card = app.agent_card
        assert card.name == "vuln_agent"
        assert card.url == "http://127.0.0.1:9102/"
        assert card.skills[0].id == "vuln"
        assert "text/plain" in card.defaultInputModes


class TestClienteSafe:
    def test_safe_call_agente_caido_degrada_a_json(self):
        from pentest_agent.a2a_client import safe_call_agent
        out = json.loads(safe_call_agent("http://127.0.0.1:59999", "ping", timeout=3))
        assert "error" in out
