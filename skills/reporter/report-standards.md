# Report standards

## Estructura del informe

1. **Resumen ejecutivo** — que se audito, alcance, veredicto en una linea.
2. **Hallazgos** — uno por vulnerabilidad, en orden de severidad.
3. **Remediacion** — accion concreta por hallazgo, priorizada igual que los
   hallazgos.

## Reglas de evidencia

- Todo hallazgo cita su fuente: salida del scan, CVE del vuln agent, o proof
  del exploit agent. Hallazgo sin cita NO entra al informe.
- La evidencia se incluye hasheada (cadena de custodia); jamas datos reales
  del cliente en el cuerpo.
- Distingue siempre: hallazgo *detectado* (version vulnerable) vs *demostrado*
  (explotado con autorizacion). El valor de venta es el segundo.

## Tono

- Directo y factual. Sin adjetivos de marketing ("grave vulnerabilidad
  catastrofica") — severidad numerica + evidencia.
- El informe final se redacta en el idioma del engagement.
