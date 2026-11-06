import { readThumb } from "./native";

// Miniaturas ligeras con límite de concurrencia. Compartido por la vista de
// progreso y la de resultados de clasificación. Las miniaturas las genera el
// sidecar (read_thumb), que soporta JPG y CR2/RAW por igual.

// Tope de miniaturas en paralelo: por DEBAJO de los 8 slots del sidecar, para
// que el listado de carpetas (fs_list_dir) y la clasificación nunca se ahoguen
// detrás de los read_thumb (pesados con CR2/RAW).
const MAX_THUMBS = 4;
let active = 0;
const queue = [];
function pump() {
  while (active < MAX_THUMBS && queue.length) {
    const job = queue.shift();
    active++;
    job().finally(() => { active--; pump(); });
  }
}
export function enqueueThumb(job) {
  return new Promise((resolve) => { queue.push(() => job().then(resolve, () => resolve(null))); pump(); });
}

// Miniatura ligera (JPEG ~KB) generada en el backend. Soporta CR2/RAW.
// Devuelve un data URL listo para <img src>. Reintenta cuando el sidecar
// responde "ocupado" (sus slots se rechazan, no se encolan) — frecuente con
// CR2 pesados — para que la tile no se quede sin foto.
export async function makeThumb(path, size = 256, attempts = 5) {
  for (let a = 0; a < attempts; a++) {
    try {
      return await readThumb(path, size);
    } catch (e) {
      const msg = String(e?.message || e);
      if (a < attempts - 1 && /ocupado|tiempo esperado/i.test(msg)) {
        await new Promise((r) => setTimeout(r, 250 + a * 300));
        continue;
      }
      throw e;
    }
  }
  return null;
}
