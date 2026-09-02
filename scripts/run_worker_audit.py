"""Auditoria A2A completa contra el worker K8s (192.168.17.53).

Requiere: start_worker_stack.sh levantado y msfrpcd vivo (SSL :55553).
Engagement ENG-K8SWORKER-2026-001 (scope: unicamente 192.168.17.53/32).
"""
import os

os.environ.setdefault("A2A_EXPLOIT_URL", "http://127.0.0.1:9104")

from langchain_core.messages import HumanMessage

from pentest_agent.a2a_team import build_a2a_supervisor

TARGET = "192.168.17.53"
PORTS = "22,80,443,179,9100,10248,10249,10250,10255,10256,30000-32767"

task = (
    f"Audita el nodo worker de Kubernetes {TARGET} (puertos: {PORTS}; el rango "
    "30000-32767 es NodePort, ahi viven las apps expuestas del cluster). "
    "Orden canonico: recon descubre puertos/servicios; vuln correlaciona CVEs "
    "reales (NVD) de cada producto+version detectado. Si hay hallazgos "
    "CRITICOS/KEV, o superficie expuesta como kubelet 10250 o apps corriendo "
    "en NodePorts, delega al exploit_agent para demostrar impacto usando SOLO "
    "los modulos allowlisted del engagement (comando no destructivo tipo 'id' "
    "o 'hostname' si exec aplica). El exploit_agent reportara el JSON del "
    "ledger tal cual. Finalmente reporter redacta y guarda el reporte "
    "markdown. Al confirmar el guardado, termina."
)

team = build_a2a_supervisor()
result = team.invoke(
    {"messages": [HumanMessage(content=task)]},
    config={"recursion_limit": 60},
)
msgs = result["messages"]
print(f"=== mensajes del grafo: {len(msgs)} ===")
for m in msgs:
    name = getattr(m, "name", "") or m.__class__.__name__
    content = m.content if isinstance(m.content, str) else str(m.content)
    print(f"--- [{name}] {content[:500]}")
print("=== FIN ===")
