"""Tests de regresion del supervisor A2A (nodo supervisor puro, HTTP fail-safe).

Cubren el bugfix del 'fin silencioso': un LLM que delega con texto plano
en vez de tool call NO debe terminar la auditoria.
"""
import os
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

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
