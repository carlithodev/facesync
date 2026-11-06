import { useEffect, useRef, useState } from "react";
import { enqueueThumb, makeThumb } from "../lib/thumbs";

// Segunda ventana: resumen tras clasificar. Mismo lenguaje visual que la de
// progreso. Stats reales del reporte + grid de carpetas con foto de muestra.

function FolderTile({ folder }) {
  const [src, setSrc] = useState(null);
  const [seen, setSeen] = useState(false); // miniatura perezosa: solo al entrar en vista
  const boxRef = useRef(null);
  const urlRef = useRef(null);

  // Observa visibilidad: la miniatura (read_thumb, pesada en CR2) solo se pide
  // cuando la tile está en pantalla, para no ahogar el sidecar ni el listado.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); } },
      { rootMargin: "300px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!seen || !folder.sample) return;
    let on = true;
    const load = (tries) =>
      enqueueThumb(() => makeThumb(folder.sample, 200)).then((url) => {
        if (!on) { if (url) URL.revokeObjectURL(url); return; }
        if (!url && tries > 0) { setTimeout(() => load(tries - 1), 500); return; }
        urlRef.current = url;
        setSrc(url);
      });
    load(2);
    return () => { on = false; if (urlRef.current) URL.revokeObjectURL(urlRef.current); };
  }, [seen, folder.sample]);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div ref={boxRef} className="relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-white/[0.03] ring-1 ring-white/[0.08]">
        {src ? (
          <img src={src} alt="" draggable={false} decoding="async" className="tile-in h-full w-full object-cover" />
        ) : (
          <div className="absolute inset-0 animate-pulse bg-white/[0.04]" />
        )}
        <span className="absolute bottom-1 right-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur">{folder.count}</span>
      </div>
      <span className="w-full truncate text-center text-[11px] leading-tight text-slate-300" title={folder.name}>{folder.name}</span>
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.025] px-4 py-3.5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-[26px] font-bold leading-none tabular-nums ${accent ? "bg-gradient-to-br from-indigo-300 to-fuchsia-300 bg-clip-text text-transparent" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

export default function ClassifyResults({ open, stats = {}, folders = [], onVerCarpetas, onClose }) {
  if (!open) return null;
  return (
    <div className="u-overlay fixed inset-0 z-[71] flex items-center justify-center bg-black/60 backdrop-blur-md p-6">
      <div className="u-sheet relative flex w-full max-w-[760px] max-h-[90vh] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#0b0c14]/95 backdrop-blur-2xl shadow-[0_30px_90px_rgba(0,0,0,0.65)]">
        <div className="pointer-events-none absolute -top-20 left-1/2 h-40 w-72 -translate-x-1/2 rounded-full bg-emerald-500/10 blur-[80px]" />

        {/* Header */}
        <div className="relative flex items-center gap-3 px-8 pt-8 pb-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-emerald-500/15 ring-1 ring-emerald-400/30">
            <svg viewBox="0 0 24 24" className="h-5 w-5 text-emerald-300" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
          </span>
          <h2 className="text-[19px] font-semibold tracking-tight">Carpetas clasificadas con éxito</h2>
        </div>

        {/* Stats */}
        <div className="relative grid grid-cols-3 gap-3 px-8">
          <Stat label="Carpetas clasificadas" value={stats.carpetas || folders.length || "—"} />
          <Stat label="Fotos clasificadas" value={stats.fotos ?? "—"} />
          <Stat label="Efectividad" value={stats.efectividad != null ? `${stats.efectividad}%` : "—"} accent />
        </div>

        {/* Grid de carpetas */}
        <div className="relative flex-1 min-h-0 overflow-auto px-8 py-5">
          {folders.length ? (
            <div className="grid grid-cols-6 gap-3">
              {folders.map((f) => <FolderTile key={f.name} folder={f} />)}
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-slate-500">Cargando carpetas…</div>
          )}
        </div>

        {/* Footer */}
        <div className="relative flex items-center justify-between border-t border-white/[0.06] px-8 py-4">
          <button onClick={onVerCarpetas}
            className="rounded-xl border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] active:scale-[0.97]">
            Ver carpetas
          </button>
          <button onClick={onClose}
            className="rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-900/30 transition hover:brightness-110 active:scale-95">
            Listo
          </button>
        </div>
      </div>
    </div>
  );
}
