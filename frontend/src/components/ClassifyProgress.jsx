import { useEffect, useRef, useState } from "react";
import { enqueueThumb as enqueue, makeThumb } from "../lib/thumbs";

// Modal centrado de progreso de clasificación. Muestra el FLUJO REAL del motor:
// el % y la fase (stage) vienen del motor; los nombres salen del Excel y las
// fotos son reales de las carpetas, con efecto de escaneo. NO toca el motor.
// Las miniaturas (JPG o CR2) las genera el sidecar vía makeThumb.

const TILES = 24; // grid 6 x 4

// Texto por FASE real del motor (el bridge envía el stage de cada evento).
const STAGE_TEXT = {
  started: () => "Leyendo el Excel y escaneando las fotos…",
  listed_images: () => "Escaneando todas las fotos…",
  extracting_references: (n) => (n ? `Buscando la referencia de ${n}…` : "Buscando las referencias…"),
  indexing_faces: () => "Preparando el índice rápido de los archivos RAW…",
  extracting_faces: (n) => (n ? `Clasificando fotos de ${n}…` : "Analizando rostros…"),
  comparing: () => "Comparando identidades…",
  copying: () => "Entregando fotos a sus carpetas…",
  reporting: () => "Generando reportes…",
  finalizing: () => "Finalizando…",
  done: () => "¡Clasificación completada!",
};
// En estas fases mostramos el nombre del alumno (van rotando).
const ROTATING_STAGES = new Set(["extracting_references", "extracting_faces"]);

// Celda con rotación SUAVE: carga la siguiente foto (esperando a que termine)
// antes de mostrarla — nunca se descarta a medias, ritmo pausado.
function ScanTile({ paths, offset, rotate }) {
  const [src, setSrc] = useState(null);
  const idx = useRef(offset);
  const cur = useRef(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let timer;
    const cycle = async () => {
      if (!paths.length || !alive.current) return;
      const path = paths[idx.current % paths.length];
      const url = await enqueue(() => makeThumb(path));
      if (!alive.current) { if (url) URL.revokeObjectURL(url); return; }
      const prev = cur.current;
      cur.current = url;
      setSrc(url);
      if (prev) setTimeout(() => URL.revokeObjectURL(prev), 700);
      if (rotate) {
        idx.current += TILES;
        timer = setTimeout(cycle, 3200 + offset * 220);
      }
    };
    cycle();
    return () => { alive.current = false; clearTimeout(timer); if (cur.current) URL.revokeObjectURL(cur.current); };
  }, [paths, offset, rotate]);

  return (
    <div className="relative aspect-[3/4] overflow-hidden rounded-xl bg-white/[0.03] ring-1 ring-white/[0.08]">
      {src ? (
        <img key={src} src={src} alt="" draggable={false} decoding="async" className="tile-in h-full w-full object-cover" />
      ) : (
        <div className="absolute inset-0 animate-pulse bg-white/[0.04]" />
      )}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="scan-band absolute inset-x-0 h-1/3 bg-gradient-to-b from-transparent via-fuchsia-200/20 to-transparent" />
      </div>
    </div>
  );
}

export default function ClassifyProgress({ open, frac, stage, folder, names = [], photoPaths = [], done, cancelling, onCancel, onClose }) {
  const pct = Math.round(Math.max(0, Math.min(1, frac || 0)) * 100);
  const [rot, setRot] = useState(0); // índice rotante del nombre

  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => setRot((r) => r + 1), 2200);
    return () => clearInterval(t);
  }, [open]);

  if (!open) return null;

  const name = names.length ? names[rot % names.length] : null;
  const textFn = STAGE_TEXT[stage];
  const action = done
    ? "¡Clasificación completada!"
    : textFn
    ? textFn(ROTATING_STAGES.has(stage) ? name : null)
    : "Procesando…";

  const hasPhotos = photoPaths.length > 0;
  const tileCount = Math.min(TILES, photoPaths.length || TILES);
  // Las fotos solo rotan durante las fases visuales largas (no al final).
  const rotate = !done && (ROTATING_STAGES.has(stage) || stage === "comparing" || stage === "indexing_faces");

  return (
    <div className="u-overlay fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-md p-6">
      <div className="u-sheet relative flex w-full max-w-[680px] max-h-[90vh] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#0b0c14]/95 backdrop-blur-2xl shadow-[0_30px_90px_rgba(0,0,0,0.65)]">
        <div className="pointer-events-none absolute -top-20 left-1/2 h-40 w-72 -translate-x-1/2 rounded-full bg-fuchsia-600/10 blur-[80px]" />

        {/* Cabecera minimalista: título + % + barra fina + fase */}
        <div className="relative px-8 pt-8 pb-5">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="text-[19px] font-semibold tracking-tight">Clasificando fotos</h2>
            <span className="text-[15px] font-semibold tabular-nums text-fuchsia-200">{pct}%</span>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400 transition-[width] duration-500 ease-out" style={{ width: `${pct}%` }} />
          </div>
          <div key={action} className="u-fade mt-3 flex items-center gap-2 text-[13px] text-slate-400">
            {done ? (
              <svg viewBox="0 0 24 24" className="h-4 w-4 text-emerald-400" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
            ) : (
              <span className="chat-typing inline-flex gap-1 text-slate-600"><span /><span /><span /></span>
            )}
            <span className="truncate">{action}</span>
            {folder && !done && <span className="ml-auto truncate text-slate-600">· {folder}</span>}
          </div>
        </div>

        {/* Grid de fotos directo, sin caja */}
        <div className="relative flex-1 min-h-0 overflow-auto px-8 pb-8">
          {hasPhotos ? (
            <div className="grid grid-cols-6 gap-2.5">
              {Array.from({ length: tileCount }).map((_, i) => (
                <ScanTile key={i} paths={photoPaths} offset={i} rotate={rotate} />
              ))}
            </div>
          ) : (
            <div className="py-12 text-center text-sm text-slate-500">Analizando las fotos…</div>
          )}
        </div>

        <div className="relative -mt-2 flex justify-end px-8 pb-7">
          {done ? (
            <button onClick={onClose}
              className="rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-900/30 transition hover:brightness-110 active:scale-95">
              Listo
            </button>
          ) : (
            <button onClick={onCancel} disabled={cancelling}
              className="rounded-xl border border-white/10 px-5 py-2.5 text-sm font-medium text-slate-300 transition hover:border-white/20 hover:bg-white/[0.06] active:scale-[0.97] disabled:opacity-50">
              {cancelling ? "Cancelando…" : "Cancelar"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
