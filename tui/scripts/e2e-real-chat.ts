// E2E real multi-turno contra sidecar + stack A2A real (LLM GLM). Verificación final plan §7.3.
import { postChat, getStatus } from "../src/api.ts";
import { streamEvents } from "../src/sse.ts";

const ac = new AbortController();
const base = await getStatus();
console.log("[status] protocol", base.protocol, "· workers up:", base.workers.filter(w => w.up).length);

// Turno 1
const r1 = await postChat("Hola. Escanea 127.0.0.1 puerto 2121 y dime qué servicio es. Sin explotar nada.");
console.log("[turn1] session", r1.session_id.slice(0, 8));
let text1 = "";
await streamEvents(r1.session_id, r1.cursor, {
  onEvent: (_id, ev, data) => {
    if (ev === "agent.activity") {
      const d = data as Record<string, unknown>;
      console.log(`  [activity] ${d.role} ${d.action}${d.detail ? ": " + String(d.detail).slice(0, 60) : ""}`);
    }
    if (ev === "chat.delta") text1 += String((data as Record<string, unknown>).text ?? "");
    if (ev === "error") console.log("  [error]", JSON.stringify(data).slice(0, 200));
  },
  onClose: () => {},
}, ac.signal);
console.log("[turn1] respuesta:", text1.slice(0, 300).replace(/\n/g, " "));

// Turno 2 — memoria de sesión
const r2 = await postChat("¿Qué servicio te dije que encontraste en ese puerto? Responde en una línea.", r1.session_id);
let text2 = "";
await streamEvents(r2.session_id, r2.cursor, {
  onEvent: (_id, ev, data) => {
    if (ev === "chat.delta") text2 += String((data as Record<string, unknown>).text ?? "");
  },
  onClose: () => {},
}, ac.signal);
console.log("[turn2] misma sesión:", r2.session_id === r1.session_id);
console.log("[turn2] respuesta:", text2.slice(0, 200).replace(/\n/g, " "));
console.log("[e2e-real] OK");
process.exit(0);
