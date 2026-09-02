"""Debug #2: bisectar la diferencia entre probe OK y tool FAIL."""
import os

from pymetasploit3.msfrpc import MsfRpcClient

print("--- A) kwargs identicos a la tool (incluye token='') ---")
try:
    c1 = MsfRpcClient(
        password="whlab-test-pass", username="msfapi", server="127.0.0.1",
        port=55553, uri="/api/", token="", ssl=True,
    )
    con = c1.consoles.console()
    print("console OK:", con.cid)
    c1.consoles.destroy(con.cid)
except Exception as e:
    print("FAIL:", type(e).__name__, str(e)[:150])

print("--- B) kwargs minimos (sin token, como debug #1) ---")
try:
    c2 = MsfRpcClient(
        password="whlab-test-pass", username="msfapi", server="127.0.0.1",
        port=55553, uri="/api/", ssl=True,
    )
    con = c2.consoles.console()
    print("console OK:", con.cid)
    c2.consoles.destroy(con.cid)
except Exception as e:
    print("FAIL:", type(e).__name__, str(e)[:150])
