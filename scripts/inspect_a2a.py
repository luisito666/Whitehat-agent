"""Inspeccion de la API de a2a-sdk instalada (drift de versiones)."""
import importlib
import inspect

import a2a
print("a2a version attr:", getattr(a2a, "__version__", "n/a"))

mods = [
    "a2a.server.apps", "a2a.server.request_handlers", "a2a.server.agent_execution",
    "a2a.server.tasks", "a2a.server.events", "a2a.types", "a2a.client", "a2a.utils",
]
for m in mods:
    try:
        mod = importlib.import_module(m)
        names = [n for n in dir(mod) if not n.startswith("_")][:25]
        print(f"OK   {m}: {names}")
    except Exception as e:
        print(f"FAIL {m} -> {type(e).__name__}: {e}")

print("\n--- signatures ---")
try:
    from a2a.server.apps import A2AStarletteApplication
    print("A2AStarletteApplication.build:", inspect.signature(A2AStarletteApplication.build))
    print("A2AStarletteApplication.__init__:", inspect.signature(A2AStarletteApplication.__init__))
except Exception as e:
    print("apps sig fail:", e)
try:
    from a2a.server.request_handlers import DefaultRequestHandler
    print("DefaultRequestHandler.__init__:", inspect.signature(DefaultRequestHandler.__init__))
except Exception as e:
    print("handler sig fail:", e)
try:
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    print("AgentExecutor methods:", [m for m in dir(AgentExecutor) if not m.startswith("_")])
except Exception as e:
    print("executor fail:", e)
try:
    from a2a.types import AgentCard, AgentSkill, Message, Part, TextPart
    print("AgentCard fields:", list(AgentCard.model_fields))
    print("AgentSkill fields:", list(AgentSkill.model_fields))
    print("Message fields:", list(Message.model_fields))
    print("TextPart fields:", list(TextPart.model_fields))
except Exception as e:
    print("types fail:", e)
try:
    from a2a.client import ClientConfig, A2ACardResolver
    import a2a.client as cl
    print("client exports:", [n for n in dir(cl) if not n.startswith("_")][:30])
except Exception as e:
    print("client fail:", e)
