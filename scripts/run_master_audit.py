"""Auditoria A2A completa contra el master K8s (192.168.17.52).

Requiere: start_master_stack.sh levantado y msfrpcd vivo (SSL :55553).
El exploit_agent solo actua dentro del engagement ENG-K8SMASTER-2026-001
(scope: unicamente 192.168.17.52/32).
"""
import os

os.environ.setdefault("A2A_EXPLOIT_URL", "http://127.0.0.1:9104")

from langchain_core.messages import HumanMessage

from pentest_agent.a2a_team import build_a2a_supervisor

TARGET = "192.168.17.52"
PORTS = ("22,80,443,2379,2380,6443,8001,8080,"
         "10248,10249,10250,10255,10256,10257,10259")

task = (
    f"Audita el master de Kubernetes {TARGET} (puertos: {PORTS}). "
    "Orden canonico: recon descubre puertos/servicios; vuln correlaciona CVEs "
    "reales (NVD) de cada producto+version detectado. Si hay servicios "
    "Kubernetes expuestos (apiserver 6443, etcd 2379, kubelet 10250) o "
    "hallazgos CRITICOS/KEV, delega al exploit_agent para demostrar impacto "
    "usando SOLO los modulos allowlisted del engagement: "
    "auxiliary/cloud/kubernetes/enum_kubernetes, auxiliary/scanner/etcd/version, "
    "auxiliary/scanner/etcd/open_key_scanner, multi/kubernetes/exec (si exec "
    "aplica, comando no destructivo tipo 'id' o 'hostname'). El exploit_agent "
    "reportara el JSON del ledger tal cual. Finalmente reporter redacta y "
    "guarda el reporte markdown. Al confirmar el guardado, termina."
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
