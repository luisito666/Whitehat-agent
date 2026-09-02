"""Consulta payloads compatibles del modulo vsftpd via RPC."""
import os

from pymetasploit3.msfrpc import MsfRpcClient

client = MsfRpcClient(
    password=os.environ.get("MSFRPCD_PASSWORD", "whlab-test-pass"),
    username="msfapi", server="127.0.0.1", port=55553, uri="/api/", ssl=True,
)
comp = client.call("module.compatible_payloads", ["exploit/unix/ftp/vsftpd_234_backdoor"])
print("crudo:", str(comp)[:200])
plist = comp.get("results") or comp.get("payloads") or []
print("total compatibles:", len(plist))
interesting = [p for p in plist if p.startswith("cmd/unix/")]
print("cmd/unix/*:", interesting[:15])
print("interact presente:", "cmd/unix/interact" in plist)
print("generic presente:", "cmd/unix/generic" in plist)
