"""Prueba de conexion directa a msfrpcd y carga de modulos (sin gate)."""
import os

os.environ.setdefault("MSFRPCD_PASSWORD", "whlab-test-pass")

from pymetasploit3.msfrpc import MsfRpcClient

client = MsfRpcClient(
    password=os.environ["MSFRPCD_PASSWORD"], username="msfapi", server="127.0.0.1",
    port=55553, uri="/api/", ssl=True,
)
print("cliente autenticado OK")
modules = client.modules.exploits
print("exploits disponibles:", len(modules))
vsftpd = [m for m in modules if "vsftpd" in m]
print("rutas vsftpd encontradas:", vsftpd)
target = vsftpd[0] if vsftpd else "exploit/unix/ftp/vsftpd_234_backdoor"
info = client.modules.use("exploit", target.removeprefix("exploit/"))
print("nombre:", info.name)
print("rank:", info.rank, "| disclos:", info.disclosuredate)
print("opciones:", sorted(info.options)[:10])
