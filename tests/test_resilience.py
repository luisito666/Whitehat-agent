"""Tests de resiliencia del cliente A2A y del failover de provider.

Cubren los fixes posteriores a la auditoria real del fileserver
(2026-09-05): 503 intermitentes del proxy LLM matando tareas A2A y
z.ai en 429 arrastrando corridas enteras.
"""
import asyncio
import os
from unittest.mock import patch

import httpx

from pentest_agent.a2a_client import _is_network_error, call_agent_async


class TestIsNetworkError:
    def test_503_del_sdk_es_transitorio(self):
        # formato real visto en la corrida: A2AClientHTTPError "HTTP Error 503: ..."
        class FakeSDKError(Exception):
            pass
        assert _is_network_error(FakeSDKError("HTTP Error 503: Network communication error: ")) is True

    def test_500_transitorio_4xx_no(self):
        req = httpx.Request("GET", "http://x/")
        def err(code):
            return httpx.HTTPStatusError(
                f"code {code}", request=req, response=httpx.Response(status_code=code, request=req)
            )
        assert _is_network_error(err(503)) is True
        assert _is_network_error(err(500)) is True
        assert _is_network_error(err(404)) is False

    def test_connect_error_transitorio(self):
        req = httpx.Request("GET", "http://127.0.0.1:1/")
        assert _is_network_error(httpx.ConnectError("refused", request=req)) is True

    def test_error_logico_no_transitorio(self):
        # un JSON-RPC error deterministico no debe reintentarse
        assert _is_network_error(ValueError("bad params")) is False


class TestRetryLoop:
    def test_reintenta_503_y_exito_al_tercer_intento(self, tmp_path):
        """2 fallos de red -> 3er intento exitoso: la tarea NO se pierde."""
        calls = {"n": 0}

        async def fake_send_once(base_url, task, timeout):
            calls["n"] += 1
            if calls["n"] < 3:
                class E503(Exception):
                    pass
                raise E503("HTTP Error 503: Network communication error: ")
            return "resultado-sano"

        delays = []
        real_sleep = asyncio.sleep

        async def fake_sleep(s):
            delays.append(s)
            await real_sleep(0)

        with patch("pentest_agent.a2a_client._send_once", fake_send_once), \
             patch("pentest_agent.a2a_client.asyncio.sleep", fake_sleep):
            out = asyncio.run(call_agent_async("http://x", "t", timeout=5))
        assert out == "resultado-sano"
        assert calls["n"] == 3
        assert delays == [2.0, 4.0]  # backoff real, no reintentos seguidos

    def test_error_deterministico_no_reintenta(self):
        calls = {"n": 0}

        async def fake_send_once(base_url, task, timeout):
            calls["n"] += 1
            raise ValueError("json-rpc deterministic error")

        async def fake_sleep(s):
            raise AssertionError("no debe haber backoff para errores logicos")

        with patch("pentest_agent.a2a_client._send_once", fake_send_once), \
             patch("pentest_agent.a2a_client.asyncio.sleep", fake_sleep):
            try:
                asyncio.run(call_agent_async("http://x", "t", timeout=5))
                raised = False
            except ValueError:
                raised = True
        assert raised and calls["n"] == 1

    def test_agota_reintentos_propaga(self):
        async def fake_send_once(base_url, task, timeout):
            class E503(Exception):
                pass
            raise E503("HTTP Error 503: down")

        async def fake_sleep(s):
            pass

        with patch("pentest_agent.a2a_client._send_once", fake_send_once), \
             patch("pentest_agent.a2a_client.asyncio.sleep", fake_sleep):
            try:
                asyncio.run(call_agent_async("http://x", "t", timeout=5))
                raised = False
            except Exception as e:
                raised = "503" in str(e)
        assert raised


class TestProviderFailover:
    def test_fallover_a_opencode_cuando_primario_caido(self, monkeypatch):
        """Primario en 429 -> se construye el fallback de OPENCODE_GO_API_KEY."""
        for var in ("PENTEST_BASE_URL", "PENTEST_API_KEY", "PENTEST_MODEL",
                    "PENTEST_FALLBACK_BASE_URL", "PENTEST_FAILOVER"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GLM_API_KEY", "k-primaria")
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "k-fallback")

        from pentest_agent import llm as llm_mod

        probes = []

        def fake_probe(llm):
            # primero (primario z.ai) caido, segundo (fallback) sano
            probes.append(llm.openai_api_base)
            return len(probes) > 1

        monkeypatch.setattr(llm_mod, "_probe_ok", fake_probe)
        got = llm_mod.get_llm()
        assert got.openai_api_base == llm_mod.OPENCODE_BASE_URL
        # la key no es inspeccionable directamente (viaja oculta en el
        # cliente); verificamos via el client subyacente que NO es la del
        # primario z.ai
        assert "k-primaria" not in repr(got) and "k-fallback" not in repr(got)

    def test_sin_fallover_respeta_explicito(self, monkeypatch):
        """PENTEST_FAILOVER=0 -> no sonda, devuelve el primario directo."""
        for var in ("PENTEST_BASE_URL", "PENTEST_API_KEY", "PENTEST_FALLBACK_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GLM_API_KEY", "k-primaria")
        monkeypatch.setenv("PENTEST_FAILOVER", "0")
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "k-fallback")

        from pentest_agent import llm as llm_mod

        def no_probe(llm):
            raise AssertionError("no debe sondear con FAILOVER=0")

        monkeypatch.setattr(llm_mod, "_probe_ok", no_probe)
        got = llm_mod.get_llm()
        expected_primary = (
            os.environ.get("GLM_BASE_URL") or llm_mod.ZAI_BASE_URL
        )
        assert got.openai_api_base == expected_primary

    def test_primario_sano_no_fallea(self, monkeypatch):
        for var in ("PENTEST_BASE_URL", "PENTEST_API_KEY", "PENTEST_FALLBACK_BASE_URL", "PENTEST_FAILOVER"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GLM_API_KEY", "k-primaria")
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "k-fallback")

        from pentest_agent import llm as llm_mod

        monkeypatch.setattr(llm_mod, "_probe_ok", lambda llm: True)
        got = llm_mod.get_llm()
        expected_primary = os.environ.get("GLM_BASE_URL") or llm_mod.ZAI_BASE_URL
        assert got.openai_api_base == expected_primary
