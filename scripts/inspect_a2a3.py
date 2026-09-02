"""Inspeccion #3: version, rutas de servidor, API de cliente, construccion de card."""
import inspect
from importlib.metadata import version

print("a2a-sdk version:", version("a2a-sdk"))

print("\n--- a2a.server.routes ---")
import a2a.server.routes as routes
print([n for n in dir(routes) if not n.startswith("_")])
for n in dir(routes):
    if "app" in n.lower() or "route" in n.lower() or "build" in n.lower():
        obj = getattr(routes, n)
        if callable(obj):
            try:
                print(f"  {n}{inspect.signature(obj)}")
            except (ValueError, TypeError):
                pass

print("\n--- BaseClient / Client ---")
from a2a.client import BaseClient, Client
for m in [n for n in dir(BaseClient) if not n.startswith("_")]:
    obj = getattr(BaseClient, m)
    if callable(obj):
        try:
            print(f"  {m}{inspect.signature(obj)}")
        except (ValueError, TypeError):
            print(f"  {m}(...)")

print("\n--- AgentCard: proto o pydantic? ---")
import a2a.types as t
print("AgentCard type:", type(t.AgentCard))
ac = t.AgentCard
print("  attrs sample:", [a for a in dir(ac) if not a.startswith("_")][:25])

print("\n--- a2a.helpers.agent_card ---")
import a2a.helpers.agent_card as h
print([n for n in dir(h) if not n.startswith("_")])
for n in dir(h):
    obj = getattr(h, n)
    if callable(obj) and not n.startswith("_"):
        try:
            print(f"  {n}{inspect.signature(obj)}")
        except (ValueError, TypeError):
            pass

print("\n--- ClientConfig ---")
from a2a.client import ClientConfig
print("ClientConfig:", type(ClientConfig), [a for a in dir(ClientConfig) if not a.startswith("_")][:20])
try:
    import inspect as i2
    print("init:", i2.signature(ClientConfig.__init__))
except Exception as e:
    print("init fail:", e)

print("\n--- request handler default helper ---")
from a2a.server.request_handlers import default_request_handler
print("default_request_handler:", inspect.signature(default_request_handler))
try:
    from a2a.server.request_handlers import DefaultRequestHandlerV2
    print("DefaultRequestHandlerV2 init:", inspect.signature(DefaultRequestHandlerV2.__init__))
except Exception as e:
    print("v2 fail:", e)

print("\n--- EventQueue / TaskUpdater ---")
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
print("TaskUpdater init:", inspect.signature(TaskUpdater.__init__))
print("TaskUpdater methods:", [n for n in dir(TaskUpdater) if not n.startswith("_")][:20])
from a2a.server.events import EventQueue
print("EventQueue methods:", [n for n in dir(EventQueue) if not n.startswith("_")][:20])
print("\n--- RequestContext ---")
from a2a.server.agent_execution import RequestContext
print("RequestContext props:", [n for n in dir(RequestContext) if not n.startswith("_")][:25])
