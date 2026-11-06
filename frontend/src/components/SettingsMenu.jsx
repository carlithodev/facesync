import { useEffect, useState } from "react";
import { call } from "../lib/sidecar";
import Icon from "./Icon";

// Engrane abajo-izquierda (estilo Studio) con dropdown: estado del motor IA +
// almacenamiento del workspace.

function fmtBytes(b) {
  if (!b) return "0 MB";
  const gb = b / 1024 ** 3;
  return gb >= 0.1 ? `${gb.toFixed(1)} GB` : `${(b / 1024 ** 2).toFixed(0)} MB`;
}

export default function SettingsMenu({ ready, roots, user }) {
  const [open, setOpen] = useState(false);
  const [storage, setStorage] = useState(null);

  useEffect(() => {
    if (!open || !ready || !roots?.length) return;
    call("storage_usage", { roots, email: user?.email_safe }).then(setStorage).catch(() => {});
  }, [open, ready, roots]);

  const frac = storage?.disk?.total ? Math.min(1, storage.total_bytes / storage.disk.total) : 0;

  return (
    <div className="absolute bottom-5 left-5 z-20">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Ajustes"
        className={`flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/[0.06] text-neutral-300 backdrop-blur-xl transition duration-300 hover:bg-white/15 ${
          open ? "rotate-90 text-white" : "hover:rotate-45"
        }`}
      >
        <Icon name="settings" className="h-5 w-5" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute bottom-14 left-0 z-20 w-64 origin-bottom-left animate-[popIn_0.18s_ease-out] overflow-hidden rounded-2xl border border-white/12 bg-white/[0.07] shadow-[0_18px_60px_rgba(0,0,0,0.55)] backdrop-blur-2xl">
            <div className="pointer-events-none absolute inset-x-0 top-0 h-12 bg-gradient-to-b from-white/10 to-transparent" />
            <p className="relative px-4 pb-1 pt-3 text-[11px] tracking-[0.2em] text-neutral-500">ESTADO</p>

            <div className="relative px-4 py-2 flex items-center gap-2 text-sm text-neutral-200">
              <Icon name="cpu" className="h-[18px] w-[18px] text-fuchsia-300/80" />
              <span className={`w-2 h-2 rounded-full ${ready ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
              {ready ? "Motor IA listo" : "Arrancando motor…"}
            </div>

            <div className="relative px-4 pb-4 pt-1">
              <div className="text-xs text-neutral-400 mb-1">Almacenamiento</div>
              <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div className="h-full bg-fuchsia-500 transition-[width] duration-700 ease-out" style={{ width: `${Math.max(4, frac * 100)}%` }} />
              </div>
              <div className="text-[11px] text-neutral-500 mt-1">
                {storage ? `${fmtBytes(storage.total_bytes)} usados${storage.disk ? ` · disco ${fmtBytes(storage.disk.total)}` : ""}` : "—"}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
