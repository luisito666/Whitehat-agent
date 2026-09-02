"""Diagnostico: respuesta cruda del RPC para consolas."""
import os

from pymetasploit3.msfrpc import MsfRpcClient, MsfRpcMethod

client = MsfRpcClient(
    password=os.environ.get("MSFRPCD_PASSWORD", "whlab-test-pass"),
    username=os.environ.get("MSFRPCD_USER", "msfapi"),
    server="127.0.0.1", port=55553, uri="/api/", ssl=True,
)
raw = client.call(MsfRpcMethod.ConsoleList)
print("ConsoleList crudo:", str(raw)[:400])
print()
print("version del server:", client.call(MsfRpcMethod.Version))
print()
raw2 = client.call(MsfRpcMethod.CoreVersion) if hasattr(MsfRpcMethod, "CoreVersion") else None
print("core.version:", str(raw2)[:200])
