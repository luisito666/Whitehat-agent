# Recon methodology

## Orden del scan

1. **Ports primero**: TCP connect scan del rango acordado en el engagement
   (nmap si esta disponible; fallback Python puro si no).
2. **Services**: banner grab de cada puerto abierto. Nunca extrapolar el
   servicio por el numero de puerto — el banner manda. Solo si el banner
   no da version, usar la heuristica de puerto conocida y marcarla como
   inferida.
3. **Fingerprint TLS/HTTP**: para puertos de control (443, 6443, 2379, 10250...):
   handshake TLS + parse del certificado (CN/SANs/issuer) y `GET /version`
   inocuo. Un cert con `CN=kube-apiserver` o SANs `kubernetes.default.svc`
   identifica el servicio sin banner.

## Reglas

- Todo resultado de nmap es autoritativo; el enriquecimiento Python solo
  lena campos vacios, jamas sobrescribe.
- Un puerto abierto sin version NO es un hallazgo — es un pendiente. Repórtalo
  como "version no identificada", no inventes.
- El output estandar es una lista de servicios: puerto, producto, version,
  fuente (banner | cert | http | heuristica | nmap).
