"""Diagnostico: stream del grafo A2A para ver la secuencia real de nodos."""
from langchain_core.messages import HumanMessage

from pentest_agent.a2a_team import build_a2a_supervisor

team = build_a2a_supervisor()
task = ("Audita el host 127.0.0.1 (puertos: 22,9000). Orden: recon descubre, "
        "vuln correlaciona CVEs de cada producto+version, reporter guarda el "
        "reporte. Al confirmar el guardado, termina.")
for i, update in enumerate(team.stream(
    {"messages": [HumanMessage(content=task)]},
    config={"recursion_limit": 50}, stream_mode="updates",
)):
    for node, payload in update.items():
        if node == "__end__":
            print(f"[{i}] END"); continue
        msgs = (payload or {}).get("messages") or []
        preview = ""
        for m in msgs:
            c = m.content if isinstance(m.content, str) else str(m.content)
            tcs = [tc.get("name") for tc in getattr(m, "tool_calls", None) or []]
            preview += f"({m.__class__.__name__}{' tc=' + str(tcs) if tcs else ''}: {c[:100]}) "
        print(f"[{i}] nodo={node}: {preview[:300]}")
