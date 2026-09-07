"""Tests de regresion del supervisor A2A (nodo supervisor puro, HTTP fail-safe).

Cubren el bugfix del 'fin silencioso': un LLM que delega con texto plano
en vez de tool call NO debe terminar la auditoria.
"""
import os
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from pentest_agent import a2a_team
from pentest_agent.a2a_team import build_a2a_supervisor


def _resp(text=None, tool_calls=None):
    return AIMessage(content=text or "", tool_calls=tool_calls or [])


_DELEGA = [{"name": "transfer_to_reporter_agent",
            "args": {"task": "redacta el reporte"}, "id": "c1", "type": "tool_call"}]
_FINISH = [{"name": "finish", "args": {"summary": "reporte listo"},
            "id": "c2", "type": "tool_call"}]


class TestSupervisorNoSilentEnd:
    def test_texto_plano_reintenta_y_delega(self):
        """Turno 1 sin tool call -> recordatorio -> turno 2 SI delega al reporter."""
        os.environ.pop("A2A_EXPLOIT_URL", None)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        # turno 1: texto plano / retry: delega / turno 3 (reporter cayo): finish
        llm.invoke.side_effect = [
            _resp(text="Delegando a reporter: redacta el reporte"),
            _resp(tool_calls=_DELEGA),
            _resp(tool_calls=_FINISH),
        ]
        team = build_a2a_supervisor(llm=llm)
        g = team.invoke({"messages": [{"role": "user", "content": "audita 127.0.0.1"}]},
                        config={"recursion_limit": 6})
        # 3 invocaciones: plain -> retry(con recordatorio) -> finish
        assert llm.invoke.call_count == 3
        # el recordatorio llego al LLM en la segunda invocacion
        second_msgs = llm.invoke.call_args_list[1][0][0]
        assert any("texto plano" in getattr(m, "content", "") for m in second_msgs)
        # el grafo SI paso por el nodo reporter (delegacion efectiva)
        names = [getattr(m, "name", "") for m in g["messages"]]
        assert "reporter" in names

    def test_dos_turnos_sin_tool_call_termina(self):
        """Si tras el recordatorio el LLM sigue sin tool call, termina (no loop)."""
        os.environ.pop("A2A_EXPLOIT_URL", None)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.invoke.side_effect = [
            _resp(text="creo que ya terminamos"),
            _resp(text="ok, fin"),
        ]
        team = build_a2a_supervisor(llm=llm)
        g = team.invoke({"messages": [{"role": "user", "content": "audita 127.0.0.1"}]},
                        config={"recursion_limit": 6})
        assert llm.invoke.call_count == 2  # plain + retry, luego END
        # no paso por ningun worker
        names = [getattr(m, "name", "") for m in g["messages"]]
        assert "reporter" not in names and "recon" not in names


_RECON = [{"name": "transfer_to_recon_agent", "args": {"task": "escanea"},
           "id": "r", "type": "tool_call"}]


class TestSupervisorAntiLoop:
    """El LLM se atasca pidiendo el MISMO worker; el grafo NO debe reventar por
    recursion_limit — fuerza el avance del pipeline y cierra con resumen."""

    def test_worker_repetido_fuerza_avance_y_cierra(self, monkeypatch):
        os.environ.pop("A2A_EXPLOIT_URL", None)
        monkeypatch.setattr(
            a2a_team, "safe_call_agent",
            lambda url, task, *a, **k: f"resultado de {url.rsplit(':', 1)[-1]}",
        )
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.invoke.return_value = AIMessage(content="", tool_calls=_RECON)  # siempre recon

        team = build_a2a_supervisor(llm=llm)
        g = team.invoke(
            {"messages": [{"role": "user", "content": "audita 10.0.0.1"}]},
            config={"recursion_limit": 40},
        )

        names = [getattr(m, "name", "") for m in g["messages"]]
        # recon se ejecuta como mucho _MAX_WORKER_CALLS veces, luego se fuerza
        assert names.count("recon") == a2a_team._MAX_WORKER_CALLS
        # el pipeline avanzo pese a que el LLM solo pedia recon
        assert "vuln" in names and "reporter" in names
        # cierre limpio: hay un mensaje final sintetico, sin excepcion de recursion
        final = g["messages"][-1]
        assert final.additional_kwargs.get("final")

    def test_techo_global_de_delegaciones(self, monkeypatch):
        """Aunque cada fase 'progrese' una vez, un LLM que nunca llama finish se
        corta en el techo global sin llegar al recursion_limit."""
        os.environ.pop("A2A_EXPLOIT_URL", None)
        monkeypatch.setattr(
            a2a_team, "safe_call_agent", lambda *a, **k: "ok")
        # el LLM rota entre los 3 workers, nunca finish
        seq = ["transfer_to_recon_agent", "transfer_to_vuln_agent",
               "transfer_to_reporter_agent"] * 20
        calls = iter(seq)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.invoke.side_effect = lambda *a, **k: AIMessage(
            content="", tool_calls=[{"name": next(calls), "args": {"task": "x"},
                                     "id": "i", "type": "tool_call"}])

        team = build_a2a_supervisor(llm=llm)
        g = team.invoke(
            {"messages": [{"role": "user", "content": "audita"}]},
            config={"recursion_limit": 40},
        )
        names = [getattr(m, "name", "") for m in g["messages"]]
        assert len([n for n in names if n in {"recon", "vuln", "reporter"}]) \
            <= a2a_team._MAX_TOTAL_DELEGATIONS
        assert g["messages"][-1].additional_kwargs.get("final")

    def test_worker_repetido_reescribe_task_a_la_fase(self, monkeypatch):
        """Al forzar recon->vuln->reporter, cada worker recibe la tarea de SU
        fase, no el 'escanea puertos' que escribio el LLM para recon."""
        os.environ.pop("A2A_EXPLOIT_URL", None)
        seen: list[str] = []

        def _stub(url, task, *a, **k):
            seen.append(task)
            return "ok"

        monkeypatch.setattr(a2a_team, "safe_call_agent", _stub)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.invoke.return_value = AIMessage(content="", tool_calls=_RECON)

        build_a2a_supervisor(llm=llm).invoke(
            {"messages": [{"role": "user", "content": "audita"}]},
            config={"recursion_limit": 40},
        )
        # recon corre con la tarea del LLM; al forzar, vuln y reporter reciben
        # la descripcion de SU fase, no el 'escanea' que era para recon
        assert seen[:2] == ["escanea", "escanea"]
        assert any("CVEs reales via NVD" in t for t in seen)
        assert any("reporte markdown final" in t for t in seen)


class TestSupervisorMemoria:
    def test_checkpointer_da_memoria_multiturno(self, monkeypatch):
        from langgraph.checkpoint.memory import InMemorySaver

        os.environ.pop("A2A_EXPLOIT_URL", None)
        monkeypatch.setattr(a2a_team, "safe_call_agent", lambda *a, **k: "ok")
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.invoke.side_effect = [
            AIMessage(content="", tool_calls=_FINISH),  # turno 1
            AIMessage(content="", tool_calls=_FINISH),  # turno 2
        ]
        team = build_a2a_supervisor(llm=llm, checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": "s1"}, "recursion_limit": 6}
        team.invoke({"messages": [{"role": "user", "content": "primer mensaje"}]}, config=cfg)
        team.invoke({"messages": [{"role": "user", "content": "segundo mensaje"}]}, config=cfg)

        # la 2a llamada al LLM vio el historial del turno 1 + el nuevo mensaje
        second_msgs = llm.invoke.call_args_list[1][0][0]
        contents = " ".join(str(getattr(m, "content", "")) for m in second_msgs)
        assert "primer mensaje" in contents and "segundo mensaje" in contents
