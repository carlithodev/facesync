import { useEffect, useState } from "react";
import { call } from "../lib/sidecar";
import { readImageDataUrl } from "../lib/native";

// Navegación lateral: usuario (avatar real) + 3 secciones + almacenamiento + motor.

const NAV = [
  ["workspace", "Workspace"],
  ["reportes", "Reportes"],
  ["exportaciones", "Exportaciones"],
];

function fmtBytes(b) {
  if (!b) return "0 MB";
  const gb = b / 1024 ** 3;
  return gb >= 0.1 ? `${gb.toFixed(1)} GB` : `${(b / 1024 ** 2).toFixed(0)} MB`;
}

export default function Sidebar({ active, onNavigate, ready, user, roots, onLogout }) {
  const [avatar, setAvatar] = useState(null);
  const [storage, setStorage] = useState(null); // {total_bytes, disk}

  useEffect(() => {
    let on = true;
    if (user?.picture && /\.(png|jpg|jpeg)$/i.test(user.picture)) {
      readImageDataUrl(user.picture).then((s) => on && setAvatar(s)).catch(() => {});
    }
    return () => { on = false; };
  }, [user]);

  useEffect(() => {
    if (!ready || !roots?.length) { setStorage(null); return; }
    let on = true;
    call("storage_usage", { roots, email: user?.email_safe })
      .then((d) => on && setStorage(d)).catch(() => {});
    return () => { on = false; };
  }, [ready, roots]);

  const frac = storage?.disk?.total ? Math.min(1, storage.total_bytes / storage.disk.total) : 0;

  return (
    <aside className="w-60 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
      {/* Usuario */}
      <div className="p-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          {avatar ? (
            <img src={avatar} alt="" className="w-10 h-10 rounded-full object-cover" />
          ) : (
            <div className="w-10 h-10 rounded-full bg-sky-600/30 flex items-center justify-center text-sky-300 font-bold">
              {(user?.name || "U").slice(0, 1).toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold truncate">{user?.name || "Usuario"}</div>
            <div className="text-xs text-sky-400">Cuenta Pro</div>
          </div>
          {onLogout && (
            <button onClick={onLogout} title="Cerrar sesión" className="text-slate-500 hover:text-red-400 px-1">⏻</button>
          )}
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-2 flex flex-col gap-1">
        {NAV.map(([key, label]) => (
          <button key={key} onClick={() => onNavigate(key)}
            className={`text-left px-3 py-2 rounded-lg text-sm font-medium transition ${
              active === key ? "bg-sky-500/15 text-sky-300" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}>
            {label}
          </button>
        ))}
      </nav>

      {/* Almacenamiento */}
      {storage && (
        <div className="px-4 py-3 border-t border-slate-800">
          <div className="text-xs text-slate-400 mb-1">Almacenamiento</div>
          <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <div className="h-full bg-sky-500" style={{ width: `${Math.max(4, frac * 100)}%` }} />
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {fmtBytes(storage.total_bytes)} usados{storage.disk ? ` · disco ${fmtBytes(storage.disk.total)}` : ""}
          </div>
        </div>
      )}

      {/* Estado motor */}
      <div className="p-3 border-t border-slate-800">
        <div className="flex items-center gap-2 text-xs">
          <span className={`w-2 h-2 rounded-full ${ready ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
          <span className="text-slate-400">{ready ? "Motor IA listo" : "Arrancando motor…"}</span>
        </div>
      </div>
    </aside>
  );
}
