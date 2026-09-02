"""Inspeccion profunda #2: localizar app-builder, tipos Part y API cliente."""
import inspect
import pkgutil

import a2a
import a2a.types

print("--- todos los submodulos de a2a ---")
for m in pkgutil.walk_packages(a2a.__path__, prefix="a2a."):
    print(" ", m.name)

print("\n--- clases *Part* / *Message* en a2a.types ---")
for n in dir(a2a.types):
    if "Part" in n or "Message" in n or n in ("Role", "TaskState"):
        obj = getattr(a2a.types, n)
        kind = type(obj).__name__
        fields = list(obj.model_fields) if hasattr(obj, "model_fields") else ""
        print(f"  {n} ({kind}) {fields}")

print("\n--- a2a.server submodules con 'app' ---")
import a2a.server as srv
for m in pkgutil.walk_packages(srv.__path__, prefix="a2a.server."):
    if "app" in m.name or "http" in m.name or "starlette" in m.name:
        print(" ", m.name)

print("\n--- buscar A2AStarletteApplication en todo el paquete ---")
import importlib
for cand in ["a2a.server.apps.starlette", "a2a.server.http", "a2a.server.fastapi",
             "a2a.server.apps", "a2a.server"]:
    try:
        mod = importlib.import_module(cand)
        hits = [n for n in dir(mod) if "App" in n or "app" in n.lower()]
        print(f"  {cand}: {hits[:12]}")
    except Exception as e:
        print(f"  {cand}: FAIL {type(e).__name__}")

print("\n--- API cliente moderna ---")
from a2a.client import ClientFactory, ClientConfig, create_client
print("create_client:", inspect.signature(create_client))
print("ClientConfig fields:", list(ClientConfig.model_fields))
from a2a.client import Client, BaseClient
meths = [m for m in dir(BaseClient) if not m.startswith("_")]
print("BaseClient methods:", meths)
for m in ["send_message", "send", "get_card", "get_agent_card", "new_message"]:
    if hasattr(BaseClient, m):
        try:
            print(f"  {m}:", inspect.signature(getattr(BaseClient, m)))
        except (ValueError, TypeError):
            print(f"  {m}: (sin signature)")
from a2a.client import A2ACardResolver
print("A2ACardResolver.__init__:", inspect.signature(A2ACardResolver.__init__))
print("A2ACardResolver methods:", [m for m in dir(A2ACardResolver) if not m.startswith("_")])

print("\n--- helpers de mensajes ---")
for mod in ["a2a.utils", "a2a.utils.task", "a2a.utils.message", "a2a.utils.proto_utils"]:
    try:
        m2 = importlib.import_module(mod)
        print(f"  {mod}:", [n for n in dir(m2) if not n.startswith("_")][:20])
    except Exception as e:
        print(f"  {mod}: FAIL")

print("\n--- version instalada ---")
from importlib.metadata import version
print("a2a-sdk:", version("a2a-sdk"))
