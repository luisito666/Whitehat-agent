"""E2E supervisor LangGraph <-> 3 subagentes A2A (requiere stack levantado).

Requiere: a2a_server en 9101/9102/9103 y el demo-server en 9000.
"""
import sys

from pentest_agent.a2a_team import run_audit

result = run_audit("127.0.0.1", ports="22,9000", recursion_limit=50)
msgs = result["messages"]
print(f"=== mensajes del grafo: {len(msgs)} ===")
for m in msgs:
    name = getattr(m, "name", "") or m.__class__.__name__
    content = m.content if isinstance(m.content, str) else str(m.content)
    print(f"--- [{name}] {content[:220]}")
print("=== FIN ===")
