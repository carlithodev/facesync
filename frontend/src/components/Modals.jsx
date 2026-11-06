import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { call } from "../lib/sidecar";
import { createExcelTemplate, openExcelFile } from "../lib/native";
import Icon from "./Icon";

// Modales glass (estilo app): CrearExcel · CrearCarpetas · Clasificar.
// Escanean el workspace (scan_assets) y reusan read_excel/folders_*/classify_start.

const base = (p) => (p || "").split(/[\\/]/).filter(Boolean).pop() || p;

function Shell({ title, subtitle, icon, onClose, children, footer, width = 600 }) {
  return (
    <div className="u-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6" onMouseDown={onClose}>
      <div className="u-sheet relative flex flex-col max-h-[88vh] overflow-hidden rounded-3xl border border-white/10 bg-[#0b0c14]/95 text-slate-100 backdrop-blur-2xl shadow-[0_30px_90px_rgba(0,0,0,0.6)]"
        style={{ width }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="pointer-events-none absolute -top-24 -right-12 h-48 w-48 rounded-full bg-fuchsia-600/12 blur-[80px]" />
        <div className="pointer-events-none absolute -bottom-28 -left-16 h-48 w-48 rounded-full bg-indigo-700/12 blur-[80px]" />

        <div className="relative flex items-start gap-3.5 px-7 pt-6 pb-4">
          {icon && (
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500/25 to-fuchsia-500/25 ring-1 ring-white/15">
              <Icon name={icon} className="h-[20px] w-[20px] text-fuchsia-200" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-[18px] font-bold leading-tight tracking-tight">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[13px] text-slate-400">{subtitle}</p>}
          </div>
          <button onClick={onClose} aria-label="Cerrar"
            className="-mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/[0.08] hover:text-white active:scale-90">✕</button>
        </div>
        <div className="relative flex-1 overflow-auto px-7 py-1">{children}</div>
        <div className="relative mt-2 flex items-center justify-between border-t border-white/[0.06] px-7 py-4">{footer}</div>
      </div>
    </div>
  );
}

const Label = ({ children }) => <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">{children}</label>;

// Dropdown custom glass (reemplaza el <select> nativo, cuya lista la dibuja el
// SO y se ve gris/plana). Popup en posición fixed para no recortarse dentro del
// modal con overflow.
function Sel({ value, onChange, options, disabled, placeholder = "—" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const btnRef = useRef(null);
  const cur = options.find((o) => o.value === value);

  const openMenu = () => {
    if (disabled) return;
    const r = btnRef.current.getBoundingClientRect();
    // Siempre JUSTO debajo del botón (anclado); si no cabe, hace scroll interno.
    setPos({ left: r.left, width: r.width, top: r.bottom + 6, maxH: Math.max(140, window.innerHeight - r.bottom - 16) });
    setOpen(true);
  };

  return (
    <>
      <button type="button" ref={btnRef} disabled={disabled} onClick={() => (open ? setOpen(false) : openMenu())}
        className={`flex h-11 w-full items-center justify-between gap-2 rounded-xl border bg-white/[0.04] px-3.5 text-sm text-slate-100 transition hover:bg-white/[0.06] focus:outline-none disabled:opacity-50 ${open ? "border-fuchsia-500/50 bg-white/[0.06]" : "border-white/10"}`}>
        <span className="truncate text-left">{cur ? cur.label : placeholder}</span>
        <Icon name="chevronDown" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && pos && createPortal(
        <>
          <div className="fixed inset-0 z-[55]" onMouseDown={() => setOpen(false)} />
          <div className="u-pop origin-top fixed z-[56] overflow-auto rounded-xl border border-white/10 bg-[#11131f]/98 backdrop-blur-xl shadow-2xl p-1.5"
            style={{ left: pos.left, top: pos.top, width: pos.width, maxHeight: pos.maxH }}>
            {options.length === 0 && <div className="px-3 py-2 text-sm text-slate-500">—</div>}
            {options.map((o) => (
              <div key={o.value} onMouseDown={() => { onChange(o.value); setOpen(false); }}
                className={`flex items-center justify-between gap-2 px-3 py-2 mb-0.5 last:mb-0 rounded-lg cursor-pointer text-sm transition ${o.value === value ? "bg-indigo-500/20 text-white" : "text-slate-200 hover:bg-white/[0.06]"}`}>
                <span className="truncate">{o.label}</span>
                {o.value === value && <Icon name="check" className="w-4 h-4 text-fuchsia-300 shrink-0" />}
              </div>
            ))}
          </div>
        </>,
        document.body
      )}
    </>
  );
}
const Ghost = ({ children, onClick, disabled }) => (
  <button onClick={onClick} disabled={disabled} className="rounded-xl border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100">{children}</button>
);
const Primary = ({ children, onClick, disabled }) => (
  <button onClick={onClick} disabled={disabled} className="rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-900/30 transition hover:brightness-110 active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100">{children}</button>
);
const inputCls = "w-full h-11 px-3.5 rounded-xl bg-white/[0.04] border border-white/10 text-sm text-slate-100 placeholder:text-slate-500 transition focus:border-fuchsia-500/50 focus:bg-white/[0.06] focus:outline-none";
const listCls = "rounded-xl bg-white/[0.02] border border-white/10 overflow-auto p-1.5";

function useAssets(roots) {
  const [assets, setAssets] = useState({ excels: [], folders: [] });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let on = true;
    call("scan_assets", { roots: roots || [] })
      .then((d) => on && setAssets({ excels: d.excels || [], folders: d.folders || [] }))
      .catch(() => {})
      .finally(() => on && setLoading(false));
    return () => { on = false; };
  }, []);
  return { assets, loading };
}

function useWorkspaceFolders(roots) {
  const [folders, setFolders] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    call("workspace_folders", { roots: roots || [] })
      .then((data) => active && setFolders(data.folders || []))
      .catch(() => {})
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);
  return { folders, loading };
}

// --------------------------------------------------------------- Crear Excel
export function CrearExcelModal({ roots, onClose, onDone }) {
  const { folders, loading } = useWorkspaceFolders(roots);
  const [name, setName] = useState("");
  const [dest, setDest] = useState("");
  const [created, setCreated] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!dest && folders[0]) setDest(folders[0]);
  }, [folders, dest]);

  const normalizedRoots = (roots || []).map((root) => String(root).replace(/\\/g, "/").replace(/\/$/, ""));
  const folderLabel = (path) => {
    const normalized = String(path || "").replace(/\\/g, "/").replace(/\/$/, "");
    const root = normalizedRoots
      .filter((candidate) => normalized === candidate || normalized.startsWith(`${candidate}/`))
      .sort((a, b) => b.length - a.length)[0];
    if (!root) return normalized;
    const relative = normalized.slice(root.length).replace(/^\//, "");
    return relative ? `${base(root)} / ${relative}` : `${base(root)} (raíz)`;
  };
  const folderOptions = folders.map((path) => ({ value: path, label: folderLabel(path) }));

  const create = async () => {
    if (!name.trim() || !dest || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const info = await createExcelTemplate(name, dest, roots || []);
      setCreated(info);
      onDone?.();
    } catch (error) {
      setMessage(String(error?.message || error));
    } finally {
      setBusy(false);
    }
  };

  const openExcel = async () => {
    if (!created || busy) return;
    setBusy(true);
    setMessage("");
    try {
      await openExcelFile(created.path, roots || []);
    } catch (error) {
      setMessage(`No pude abrir el Excel: ${String(error?.message || error)}`);
    } finally {
      setBusy(false);
    }
  };

  if (created) {
    return (
      <Shell title="Excel creado" subtitle="La plantilla se guardó correctamente." icon="check" onClose={onClose}
        footer={<><Ghost onClick={openExcel} disabled={busy}>{busy ? "Abriendo…" : "Abrir Excel"}</Ghost><Primary onClick={onClose}>Listo</Primary></>}>
        <div className="rounded-2xl border border-emerald-400/25 bg-emerald-400/[0.07] p-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-400/10 text-emerald-300 ring-1 ring-emerald-400/20">
              <Icon name="check" className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-emerald-100">El Excel “{created.name}” se creó correctamente.</p>
              <p className="mt-1 text-xs text-slate-400">Se guardó en la carpeta:</p>
              <p className="mt-0.5 break-all text-xs leading-relaxed text-slate-500">{dest}</p>
            </div>
          </div>
        </div>
        {message && <div className="mt-3 rounded-xl border border-red-400/25 bg-red-400/10 p-3 text-sm text-red-200">{message}</div>}
      </Shell>
    );
  }

  return (
    <Shell title="Crear Excel" subtitle="Crea una plantilla lista para registrar alumnos y códigos de foto." icon="sheet" onClose={onClose}
      footer={<><Ghost onClick={onClose}>Cancelar</Ghost><Primary onClick={create} disabled={!name.trim() || !dest || busy}>{busy ? "Creando…" : "Crear Excel"}</Primary></>}>
      <Label>Nombre del Excel</Label>
      <div className="relative">
        <input autoFocus value={name} onChange={(event) => setName(event.target.value.replace(/\.xlsx$/i, ""))} onKeyDown={(event) => event.key === "Enter" && create()}
          placeholder="Ej. 501M" className={`${inputCls} pr-16`} />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">.xlsx</span>
      </div>
      <div className="h-4" />
      <Label>Dónde lo quieres guardar</Label>
      <Sel value={dest} onChange={setDest} options={folderOptions} disabled={loading} placeholder={loading ? "Cargando carpetas…" : "Selecciona una carpeta"} />

      {!loading && folderOptions.length === 0 && <div className="mt-3 rounded-xl border border-amber-400/25 bg-amber-400/10 p-3 text-sm text-amber-200">Agrega primero una carpeta al workspace.</div>}
      {message && <div className="mt-3 rounded-xl border border-red-400/25 bg-red-400/10 p-3 text-sm text-red-200">{message}</div>}
    </Shell>
  );
}

// ----------------------------------------------------------- Crear carpetas
export function CrearCarpetasModal({ roots, onClose, onDone }) {
  const { assets, loading } = useAssets(roots);
  const [excel, setExcel] = useState("");
  const [cols, setCols] = useState([]);
  const [col, setCol] = useState("");
  const [dest, setDest] = useState("");
  const [prev, setPrev] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!excel && assets.excels[0]) setExcel(assets.excels[0]); }, [assets]);
  useEffect(() => { if (!dest && assets.folders[0]) setDest(assets.folders[0]); }, [assets]);
  useEffect(() => {
    if (!excel) return;
    call("read_excel", { path: excel }).then((d) => { setCols(d.columns || []); setCol((d.columns || [])[0] || ""); }).catch(() => setCols([]));
  }, [excel]);
  useEffect(() => {
    if (!excel || !col) { setPrev(null); return; }
    call("folders_preview", { path: excel, column: col }).then(setPrev).catch(() => setPrev(null));
  }, [excel, col]);

  const crear = async () => {
    if (!excel || !col || !dest) return;
    setBusy(true);
    try { const d = await call("folders_create", { destino: dest, path: excel, column: col }); setRes({ ok: true, ...d }); onDone && onDone(); }
    catch (e) { setRes({ ok: false, message: String(e.message || e) }); }
    finally { setBusy(false); }
  };

  const exOpts = assets.excels.map((p) => ({ value: p, label: base(p) }));
  const dirOpts = assets.folders.map((p) => ({ value: p, label: base(p) }));

  return (
    <Shell title="Crear carpetas" subtitle="Crea una carpeta por registro del Excel/CSV de referencia." icon="folder" onClose={onClose}
      footer={<><Ghost onClick={onClose}>Cancelar</Ghost><Primary onClick={crear} disabled={!excel || !col || !dest || busy}>{busy ? "Creando…" : "Crear carpetas"}</Primary></>}>
      <Label>Excel de referencia</Label>
      <Sel value={excel} onChange={setExcel} options={exOpts} disabled={loading} />
      <div className="h-3" />
      <Label>Columna de nombres</Label>
      <Sel value={col} onChange={setCol} options={cols.map((c) => ({ value: c, label: c }))} />
      <div className="h-3" />
      <Label>Carpeta destino</Label>
      <Sel value={dest} onChange={setDest} options={dirOpts} disabled={loading} />
      <div className="flex items-center justify-between mt-4 mb-1.5">
        <h3 className="font-semibold text-[15px]">Vista previa</h3>
        <span className="text-sm text-fuchsia-300">{prev ? `${prev.count} carpeta(s)` : ""}</span>
      </div>
      <div className={`${listCls} max-h-40 text-sm`}>
        {!prev ? <span className="text-slate-500 px-2 py-1 block">—</span>
          : prev.names?.slice(0, 200).map((n, i) => (
            <div key={i} className="flex items-center gap-2.5 px-2.5 py-1.5 mb-0.5 last:mb-0 rounded-lg truncate text-slate-300 hover:bg-white/[0.04]">
              <Icon name="folder" className="w-[15px] h-[15px] text-amber-300/70 shrink-0" /> <span className="truncate">{n}</span>
            </div>
          ))}
      </div>
      {res && <div className={`mt-2 text-sm ${res.ok ? "text-emerald-300" : "text-red-300"}`}>{res.ok ? `✓ ${res.created}/${res.total} carpetas creadas en ${base(dest)}` : `⚠ ${res.message}`}</div>}
    </Shell>
  );
}

// -------------------------------------------------------------- Clasificar
export function ClasificarModal({ roots, onClose, onClassify }) {
  const { assets, loading } = useAssets(roots);
  const [excel, setExcel] = useState("");
  const [cols, setCols] = useState([]);
  const [nameCol, setNameCol] = useState("");
  const [refCol, setRefCol] = useState("");
  const [dest, setDest] = useState("");
  const [q, setQ] = useState("");
  const [sources, setSources] = useState([]);

  useEffect(() => { if (!excel && assets.excels[0]) setExcel(assets.excels[0]); }, [assets]);
  useEffect(() => { if (!dest && assets.folders[0]) setDest(assets.folders[0]); }, [assets]);
  useEffect(() => {
    if (!excel) return;
    call("read_excel", { path: excel }).then((d) => {
      const c = d.columns || []; setCols(c); setNameCol(c[0] || ""); setRefCol(c[1] || c[0] || "");
    }).catch(() => setCols([]));
  }, [excel]);

  const toggle = (p) => setSources((s) => s.includes(p) ? s.filter((x) => x !== p) : [...s, p]);
  const folders = assets.folders.filter((p) => !q || base(p).toLowerCase().includes(q.toLowerCase()));

  const falta = [];
  if (!excel) falta.push("Excel");
  if (!nameCol) falta.push("columna de nombres");
  if (!refCol) falta.push("columna de referencia");
  if (sources.length === 0) falta.push("carpeta origen");
  if (!dest) falta.push("carpeta destino");

  const iniciar = () => {
    if (falta.length) return;
    onClassify({ excel, name_column: nameCol, reference_column: refCol, sources, destino: dest });
    onClose();
  };

  const exOpts = assets.excels.map((p) => ({ value: p, label: base(p) }));
  const dirOpts = assets.folders.map((p) => ({ value: p, label: base(p) }));
  const colOpts = cols.map((c) => ({ value: c, label: c }));

  return (
    <Shell title="Clasificar fotos" subtitle="Reconocimiento facial por lotes usando tu Excel de referencia." icon="photosCheck" onClose={onClose} width={640}
      footer={
        <div className="flex items-center justify-between w-full">
          <span className={`text-sm ${falta.length ? "text-amber-400" : "text-emerald-300"}`}>{falta.length ? `Falta: ${falta.join(", ")}` : "Listo para clasificar."}</span>
          <div className="flex gap-2"><Ghost onClick={onClose}>Cancelar</Ghost><Primary onClick={iniciar} disabled={falta.length > 0}>Iniciar clasificación</Primary></div>
        </div>
      }>
      <Label>Excel de referencia</Label>
      <Sel value={excel} onChange={setExcel} options={exOpts} disabled={loading} />
      <div className="grid grid-cols-2 gap-3 mt-3">
        <div><Label>Columna de nombres</Label><Sel value={nameCol} onChange={setNameCol} options={colOpts} /></div>
        <div><Label>Columna de referencia / foto</Label><Sel value={refCol} onChange={setRefCol} options={colOpts} /></div>
      </div>
      <div className="mt-3"><Label>Carpetas origen (una o varias)</Label>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar carpeta…" className={`${inputCls} mb-1.5`} />
        <div className={`${listCls} max-h-40`}>
          {loading ? <div className="text-sm text-slate-500 px-2 py-1">Escaneando…</div>
            : folders.map((p) => {
              const on = sources.includes(p);
              return (
                <label key={p} className={`flex items-center gap-2.5 px-2.5 py-2 mb-1 last:mb-0 text-sm cursor-pointer rounded-xl transition ${on ? "bg-indigo-500/15 ring-1 ring-indigo-400/30" : "hover:bg-white/[0.05]"}`}>
                  <input type="checkbox" checked={on} onChange={() => toggle(p)} className="accent-fuchsia-500 w-4 h-4" />
                  <span className="w-7 h-7 rounded-lg bg-white/[0.06] border border-white/10 flex items-center justify-center shrink-0">
                    <Icon name="folder" className="w-[14px] h-[14px] text-amber-300/70" />
                  </span>
                  <span className="truncate text-slate-200">{base(p)}</span>
                </label>
              );
            })}
        </div>
        <div className="text-xs text-fuchsia-300 mt-1.5">{sources.length} carpeta(s) seleccionada(s)</div>
      </div>
      <div className="mt-3"><Label>Carpeta destino</Label><Sel value={dest} onChange={setDest} options={dirOpts} disabled={loading} /></div>
    </Shell>
  );
}
