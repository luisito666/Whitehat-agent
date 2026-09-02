"""Interactua con la sesion existente de msf (session 1) con polling."""
import time

from pymetasploit3.msfrpc import MsfRpcClient

client = MsfRpcClient(
    password="whlab-test-pass", username="msfapi", server="127.0.0.1",
    port=55553, uri="/api/", ssl=True,
)
sess = client.sessions.list
print("sesiones vivas:", {k: v.get("desc") for k, v in sess.items()})
if not sess:
    raise SystemExit("no hay sesion; correr msf_debug_interact.py primero")
sid = list(sess.keys())[0]
sh = client.sessions.session(sid)
sh.write("id\n")
for i in range(8):
    time.sleep(1)
    out = sh.read()
    if out:
        print(f"[intento {i+1}] output:", out[:200])
        break
else:
    print("sin output despues de 8s (sesion viva pero callada)")
