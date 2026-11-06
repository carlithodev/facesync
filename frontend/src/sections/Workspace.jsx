import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { call, cancel } from "../lib/sidecar";
import { pickFolder, pickFile, readImageDataUrl, isImage, isRaw } from "../lib/native";
import { makeThumb } from "../lib/thumbs";
import ChatPanel from "../components/ChatPanel";
import Icon from "../components/Icon";
import { CrearExcelModal, CrearCarpetasModal, ClasificarModal } from "../components/Modals";
import ClassifyProgress from "../components/ClassifyProgress";
import ClassifyResults from "../components/ClassifyResults";
import icoExcel from "../assets/workspace/excel.png";
import icoCarpeta from "../assets/workspace/carpeta.png";
import icoClasificar from "../assets/workspace/clasificarfotos.png";
import icoRefresh from "../assets/workspace/refresh.png";
import icoAddFile from "../assets/workspace/aggarchivo.png";
import icoAddFolder from "../assets/workspace/aggcarpeta.png";

const TAURI = typeof window !== "undefined" && window.__TAURI__;

// Panel con esquinas redondeadas (arriba y abajo) y borde sutil, mismo fondo de
// siempre. Topa los bordes (sin margen), solo se redondean las esquinas.
const CARD = "overflow-hidden rounded-2xl ring-1 ring-white/[0.06]";

// Agarradero invisible para redimensionar. La división visual la da el borde
// redondeado del panel central; aquí solo aportamos la zona de arrastre y el
// cursor. Un brillo muy sutil al pasar el cursor confirma que es ajustable.
function Splitter({ onDown }) {
  return (
    <div onMouseDown={onDown}
      className="group w-2 shrink-0 self-stretch cursor-col-resize flex items-center justify-center">
      <div className="h-16 w-[3px] rounded-full bg-white/0 transition-colors duration-150 group-hover:bg-white/15" />
    </div>
  );
}

export default function Workspace({ user, roots, setRoots }) {
  const [tree, setTree] = useState({});
  const [viewer, setViewer] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [rot, setRot] = useState(0);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const panRef = useRef(null);
  const imgRef = useRef(null);              // visor: aplicamos el pan directo al DOM
  const panPos = useRef({ x: 0, y: 0 });    // posición de pan en curso (sin re-render)
  const loadTok = useRef(0);      // descarta cargas obsoletas al cambiar rápido de imagen
  const lastUrl = useRef(null);   // objectURL actual, para liberarlo

  // Libera el objectURL al desmontar (evita fugas de memoria con miles de fotos).
  useEffect(() => () => { if (lastUrl.current) URL.revokeObjectURL(lastUrl.current); }, []);

  // Paneles redimensionables. NO se persisten: vuelven al default cada sesión.
  const [leftW, setLeftW] = useState(280);
  const [rightW, setRightW] = useState(360);
  const [dragging, setDragging] = useState(false);
  const splitRef = useRef(null);
  const startSplit = (side, e) => {
    splitRef.current = { side, startX: e.clientX, startW: side === "left" ? leftW : rightW };
    setDragging(true);
    e.preventDefault();
  };
  const moveSplit = (e) => {
    const s = splitRef.current;
    if (!s) return;
    const dx = e.clientX - s.startX;
    const c = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    // Máximo por panel proporcional al ancho -> en pantallas chicas no ahoga el
    // centro; deja siempre ~44% para el contenido.
    const cap = Math.max(240, Math.floor(window.innerWidth * 0.30));
    if (s.side === "left") setLeftW(c(s.startW + dx, 170, Math.min(520, cap)));
    else setRightW(c(s.startW - dx, 190, Math.min(680, cap)));
  };
  const endSplit = () => { if (splitRef.current) { splitRef.current = null; setDragging(false); } };

  // Responsivo: al cambiar el tamaño de la ventana, encoge los paneles para que
  // quepan bien en pantallas chicas/medianas (cada uno ≤30% del ancho).
  useEffect(() => {
    const onResize = () => {
      const cap = Math.max(200, Math.floor(window.innerWidth * 0.30));
      setLeftW((w) => Math.min(w, cap));
      setRightW((w) => Math.min(w, cap));
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const [ctx, setCtx] = useState(null);
  const [addMenu, setAddMenu] = useState(false);
  const [modal, setModal] = useState(null);
  const [proceso, setProceso] = useState({ running: false, mensaje: "Sin proceso activo", frac: 0 });
  const [classify, setClassify] = useState(null); // vista de progreso: {folder, names, photos, done}
  const classifyJob = useRef(null); // id del job de clasificación en curso (para cancelar)
  const [results, setResults] = useState(null);   // 2da ventana: {stats, folders, destino}
  const [dlg, setDlg] = useState(null); // diálogo glass: {title,label,value,placeholder,prompt,danger,confirmText,onOk}

  const askPrompt = (o) => setDlg({ prompt: true, confirmText: "Aceptar", value: "", ...o });
  const askConfirm = (o) => setDlg({ prompt: false, confirmText: "Eliminar", danger: true, ...o });

  useEffect(() => {
    if (!TAURI) return;
    let un;
    let disposed = false;
    window.__TAURI__.event.listen("tauri://drag-drop", async (e) => {
      const paths = e.payload?.paths || [];
      if (!paths.length) return;
      try {
        const { dirs } = await call("dirs_for_paths", { paths });
        if (dirs?.length) { const next = Array.from(new Set([...(roots || []), ...dirs])); setRoots(next); dirs.forEach(listDir); }
      } catch {}
    }).then((u) => { if (disposed) u(); else un = u; }).catch(() => {});
    return () => { disposed = true; if (un) un(); };
  }, [roots]);

  const listDir = useCallback(async (path) => {
    try { const d = await call("fs_list_dir", { path }); setTree((t) => ({ ...t, [path]: d })); }
    catch (e) { setTree((t) => ({ ...t, [path]: { error: String(e.message || e) } })); }
  }, []);
  // Estable salvo cuando cambia el árbol: durante pan/zoom/etc. no se recrea, así
  // FileTree (memo) no re-renderiza en cascada.
  const toggle = useCallback((path) => {
    setTree((t) => {
      if (!t[path]) return t; // abrir: lo hace listDir abajo
      // cerrar: quita el nodo Y todos sus descendientes, para que al reabrir
      // empiece colapsado (si no, los hijos abiertos reaparecen "solos").
      const prefix = path + "/";
      const next = {};
      for (const k of Object.keys(t)) {
        if (k === path || k.startsWith(prefix)) continue;
        next[k] = t[k];
      }
      return next;
    });
    if (!tree[path]) listDir(path);
  }, [tree, listDir]);

  // Refresca SOLO las carpetas ya abiertas (las que tienen datos en el árbol),
  // usando sus claves reales. No abre nada que estuviera colapsado: así una
  // acción nunca expande carpetas solas. Ignora argumentos a propósito.
  const reloadOpen = useCallback(() => {
    Object.keys(tree).forEach((k) => { if (tree[k] && !tree[k].error) listDir(k); });
  }, [tree, listDir]);

  const addCarpeta = async () => { setAddMenu(false); const p = await pickFolder(); if (!p) return; const next = Array.from(new Set([...(roots || []), p])); setRoots(next); reloadOpen(p); };
  const addArchivos = async () => {
    setAddMenu(false);
    if (!roots?.length) { await addCarpeta(); return; }
    const f = await pickFile([{ name: "Archivos", extensions: ["*"] }]);
    if (f) { try { await call("fs_copy_files", { target_dir: roots[0], files: [f] }); reloadOpen(roots[0]); } catch {} }
  };

  const openFile = useCallback(async (dir, name) => {
    const path = `${dir}/${name}`;
    setZoom(1); setRot(0); setPan({ x: 0, y: 0 }); panPos.current = { x: 0, y: 0 };
    const tok = ++loadTok.current;
    // Libera la imagen anterior antes de cargar otra (no acumular memoria).
    if (lastUrl.current) { URL.revokeObjectURL(lastUrl.current); lastUrl.current = null; }
    if (!isImage(name)) { setViewer({ name, src: null }); return; }
    setViewer({ name, src: null, loading: true });
    try {
      // CR2/RAW: el webview no los decodifica -> usamos su preview (sidecar).
      // JPG/PNG: carga directa a calidad completa.
      const dataUrl = isRaw(name) ? await makeThumb(path, 1800) : await readImageDataUrl(path);
      if (tok !== loadTok.current) return; // llegó un clic más nuevo: descartar
      if (!dataUrl) { setViewer({ name, src: null, err: "Sin previsualización disponible." }); return; }
      let src = dataUrl;
      try {
        const blob = await (await fetch(dataUrl)).blob();
        if (tok !== loadTok.current) return;
        src = URL.createObjectURL(blob);
        lastUrl.current = src;
      } catch {}
      setViewer({ name, src });
    } catch (e) {
      if (tok !== loadTok.current) return;
      setViewer({ name, src: null, err: String(e.message || e) });
    }
  }, []);

  const onContext = useCallback((e, path, isDir) => {
    e.preventDefault();
    setCtx({ x: e.clientX, y: e.clientY, path, isDir, parent: isDir ? path : path.slice(0, path.lastIndexOf("/")), isRoot: (roots || []).includes(path) });
  }, [roots]);
  const ctxNueva = () => {
    const p = ctx.path; setCtx(null);
    askPrompt({ title: "Nueva carpeta", label: "Nombre de la carpeta", placeholder: "Mi carpeta",
      onOk: async (n) => { n = (n || "").trim(); if (!n) return; try { await call("fs_new_folder", { parent: p, name: n }); reloadOpen(p); } catch {} } });
  };
  const ctxAgregar = async () => { const path = ctx.path; setCtx(null); const f = await pickFile([{ name: "Archivos", extensions: ["*"] }]); if (f) { try { await call("fs_copy_files", { target_dir: path, files: [f] }); reloadOpen(path); } catch {} } };
  const ctxRenombrar = () => {
    const p = ctx.path, parent = ctx.parent, cur = ctx.path.split("/").pop(); setCtx(null);
    askPrompt({ title: "Renombrar", label: "Nuevo nombre", value: cur,
      onOk: async (nn) => { nn = (nn || "").trim(); if (!nn || nn === cur) return; try { await call("fs_rename", { path: p, new_name: nn }); reloadOpen(parent); } catch {} } });
  };
  const ctxEliminar = () => {
    const p = ctx.path, parent = ctx.parent, isRoot = ctx.isRoot, name = ctx.path.split("/").pop(); setCtx(null);
    if (isRoot) {
      askConfirm({ title: "Quitar del workspace", label: `¿Quitar "${name}" del workspace? Sus archivos no se borrarán.`, confirmText: "Quitar", danger: false,
        onOk: () => setRoots((roots || []).filter((r) => r !== p)) });
      return;
    }
    askConfirm({ title: "Eliminar", label: `¿Eliminar "${name}"? Se enviará a la papelera cuando esté disponible.`,
      onOk: async () => { try { await call("fs_delete", { path: p }); reloadOpen(parent); } catch (e) { setProceso({ running: false, mensaje: `Error: ${String(e.message || e)}`, frac: 0 }); } } });
  };

  // Lista las carpetas de alumnos del destino con su conteo y una foto de
  // muestra (la primera). Lo hace EN PARALELO (8 a la vez) y avisa cada carpeta
  // conforme llega (onItem) para que aparezcan al instante, no al final.
  // Lista un directorio reintentando cuando el sidecar responde "ocupado": sus 8
  // slots se rechazan en vez de encolarse, así que un read_thumb pesado (CR2)
  // podria tumbar el listado. Reintentar (es transitorio) garantiza 0 carpetas
  // perdidas. Devuelve null solo si falla por una razon que no sea "ocupado".
  const listDirSafe = async (path, attempts = 8) => {
    for (let a = 0; a < attempts; a++) {
      try {
        return await call("fs_list_dir", { path });
      } catch (e) {
        const msg = String(e?.message || e);
        if (a < attempts - 1 && /ocupado|tiempo esperado/i.test(msg)) {
          await new Promise((r) => setTimeout(r, 200 + a * 250));
          continue;
        }
        return null;
      }
    }
    return null;
  };

  const collectFolders = async (destino, onItem, onCount) => {
    const EXCLUDE = new Set(["Pendientes", "conflictos_identidad", "_pendientes_revision"]);
    const dd = await listDirSafe(destino);
    const dirs = (dd?.dirs || []).filter((s) => !EXCLUDE.has(s));
    onCount?.(dirs.length); // conteo real de carpetas, al instante (no depende del streaming)
    const out = [];
    let i = 0;
    const worker = async () => {
      while (i < dirs.length) {
        const sub = dirs[i++];
        const subPath = `${destino}/${sub}`;
        const sd = await listDirSafe(subPath);
        const imgs = (sd?.files || []).filter(isImage);
        if (imgs.length) {
          const item = { name: sub, sample: `${subPath}/${imgs[0]}`, count: imgs.length };
          out.push(item);
          onItem?.(item);
        }
      }
    };
    // 4 workers (no 8): deja slots del sidecar para los read_thumb y la
    // clasificacion, reduciendo los rechazos "ocupado" antes de reintentar.
    await Promise.all(Array.from({ length: Math.min(4, dirs.length || 1) }, worker));
    return out;
  };

  const runClassify = async ({ excel, name_column, reference_column, sources, destino }) => {
    setProceso({ running: true, mensaje: "Clasificando…", frac: 0 });

    // --- Datos para la vista de progreso (representativo; NO toca el motor) ---
    const srcList = (Array.isArray(sources) ? sources : [sources]).filter(Boolean);
    const baseName = (p) => p.split(/[\\/]/).filter(Boolean).pop() || p;
    const folder = srcList.length
      ? baseName(srcList[0]) + (srcList.length > 1 ? ` +${srcList.length - 1}` : "")
      : "carpeta seleccionada";
    setClassify({ folder, names: [], photos: [], done: false });
    // nombres de alumnos desde el Excel
    call("folders_preview", { path: excel, column: name_column })
      .then((d) => setClassify((c) => (c ? { ...c, names: d?.names || [] } : c)))
      .catch(() => {});
    // muestra de fotos reales de las carpetas origen (baja 1 nivel si la
    // carpeta elegida no tiene imágenes directas, p. ej. carpeta contenedora)
    (async () => {
      const photos = [];
      const addFrom = async (dir, depth) => {
        if (photos.length >= 60) return;
        let d;
        try { d = await call("fs_list_dir", { path: dir }); } catch { return; }
        for (const f of d?.files || []) {
          if (isImage(f)) { photos.push(`${dir}/${f}`); if (photos.length >= 60) return; }
        }
        if (depth > 0) {
          for (const sub of (d?.dirs || []).slice(0, 15)) {
            await addFrom(`${dir}/${sub}`, depth - 1);
            if (photos.length >= 60) return;
          }
        }
      };
      for (const s of srcList) { await addFrom(s, 1); if (photos.length >= 60) break; }
      setClassify((c) => (c ? { ...c, photos } : c));
    })();

    let _lastProg = 0;
    try {
      const d = await call("classify_start", {
        excel,
        name_column,
        reference_column,
        sources,
        destino,
        email: user?.email_safe || user?.email || "",
      },
        (p) => {
          const now = Date.now();
          const frac = Number.isFinite(p.frac) ? p.frac : 0;
          // Throttle: máx ~8 actualizaciones/s (evita re-renders en ráfaga).
          if (now - _lastProg < 120 && frac < 1) return;
          _lastProg = now;
          setProceso({ running: true, mensaje: p.mensaje || p.message || "Procesando…", frac, stage: p.stage || "" });
        },
        (id) => { classifyJob.current = id; }); // id del job para poder cancelar
      // Cancelado por el usuario: cerrar progreso sin abrir resultados.
      if (d?.estado === "cancelado") {
        setProceso({ running: false, mensaje: "Clasificación cancelada.", frac: 0 });
        setClassify(null);
        reloadOpen();
        return;
      }
      setProceso({ running: false, mensaje: d.mensaje || "Clasificación completada.", frac: 1 });
      // --- 2da ventana: resultados (casi instantánea). Stats inmediatos del
      // reporte; las carpetas con su foto de muestra se llenan en segundo plano.
      const fotos = d.archivos_entregados_totales ?? d.total_fotos_copiadas ?? 0;
      const analizadas = d.total_fotos_analizadas ?? 0;
      const efectividad = d.diagnostico?.porcentaje_entrega != null
        ? Math.round(d.diagnostico.porcentaje_entrega)
        : d.metadata?.porcentaje_entrega != null
        ? Math.round(d.metadata.porcentaje_entrega)
        : d.diagnostico?.porcentaje_clasificado != null
        ? Math.round(d.diagnostico.porcentaje_clasificado)
        : Math.round((100 * fotos) / Math.max(1, analizadas));
      setClassify(null);
      setResults({ stats: { carpetas: 0, fotos, efectividad }, folders: [], destino: d.destino });
      collectFolders(
        d.destino,
        (item) => setResults((r) => (r ? { ...r, folders: [...r.folders, item] } : r)),
        (n) => setResults((r) => (r ? { ...r, stats: { ...r.stats, carpetas: n } } : r)),
      );
      reloadOpen();
    } catch (e) {
      setProceso({ running: false, mensaje: `Error: ${String(e.message || e)}`, frac: 0 });
      setClassify(null);
    }
  };

  // Cancela la clasificación en curso: pide al motor detenerse (cancel_event) y
  // marca la vista como "cancelando". Lo ya copiado se conserva.
  const cancelClassify = useCallback(() => {
    const id = classifyJob.current;
    if (id) cancel(id).catch(() => {});
    setClassify((c) => (c ? { ...c, cancelling: true } : c));
    setProceso((p) => ({ ...p, mensaje: "Cancelando…" }));
  }, []);

  const CARDS = [
    { key: "excel", img: icoExcel, title: "Crear Excel", desc: "Genera tu plantilla de alumnos y códigos" },
    { key: "carpetas", img: icoCarpeta, title: "Crear carpetas", desc: "Crea la estructura de carpetas" },
    { key: "clasificar", img: icoClasificar, title: "Clasificar fotos", desc: "Reconocimiento facial por lotes" },
  ];

  return (
    <div className={`h-full flex text-slate-100 ${dragging ? "cursor-col-resize select-none" : ""}`}
      onMouseMove={moveSplit} onMouseUp={endSplit} onMouseLeave={endSplit}>
      {/* IZQUIERDA: explorador estilo Apple/Finder */}
      <div style={{ width: leftW }} className={`shrink-0 flex flex-col min-h-0 ${CARD}`}>
        <div className="px-3 pt-4 pb-2">
          <h2 className="text-[15px] font-semibold px-1 mb-2.5">Mi espacio</h2>
          <div className="relative">
            <button onClick={() => setAddMenu((v) => !v)}
              className="w-full h-9 rounded-xl bg-white/[0.06] border border-white/10 hover:bg-white/[0.1] active:scale-[0.98] active:bg-white/[0.14] text-[13px] font-medium flex items-center justify-center gap-2 transition duration-100">
              <span className="text-fuchsia-300/90">＋</span> Nueva carpeta / archivo
            </button>
            {addMenu && (
              <div className="u-pop origin-top absolute z-30 mt-1.5 w-full rounded-xl border border-white/10 bg-[#0d0f1a]/95 backdrop-blur-xl overflow-hidden shadow-2xl py-1.5">
                <button onClick={addArchivos} className="w-full flex items-center gap-2.5 text-left px-3 py-[7px] text-[13px] text-slate-200 hover:bg-white/[0.07]">
                  <Icon name="fileePlus" className="w-[15px] h-[15px] opacity-80" /> Archivos
                </button>
                <button onClick={addCarpeta} className="w-full flex items-center gap-2.5 text-left px-3 py-[7px] text-[13px] text-slate-200 hover:bg-white/[0.07]">
                  <Icon name="folder" className="w-[15px] h-[15px] opacity-80" /> Carpeta
                </button>
              </div>
            )}
          </div>
          <div className="flex items-center justify-between mt-4 mb-1 px-1">
            <span className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Explorador</span>
            <div className="flex gap-0.5">
              <Tbtn title="Refrescar" onClick={() => reloadOpen(...(roots || []))} img={icoRefresh} />
              <Tbtn title="Agregar archivos" onClick={addArchivos} img={icoAddFile} />
              <Tbtn title="Nueva carpeta" onClick={addCarpeta} img={icoAddFolder} />
            </div>
          </div>
        </div>
        <FileTree roots={roots} tree={tree} toggle={toggle} openFile={openFile} onContext={onContext} />
      </div>

      <Splitter onDown={(e) => startSplit("left", e)} />

      {/* CENTRO: visor + acciones + proceso (plano) */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0 overflow-auto p-6 gap-5">
        <div className="text-sm font-medium text-slate-300">{viewer ? viewer.name : "Selecciona un archivo"}</div>
        <div className="flex-1 min-h-56 rounded-[24px] border border-white/10 bg-white/[0.045] backdrop-blur-xl flex items-center justify-center overflow-hidden relative shadow-[0_20px_60px_rgba(0,0,0,0.4)]"
          onMouseDown={(e) => { if (viewer?.src) { panRef.current = { sx: e.clientX, sy: e.clientY, ox: pan.x, oy: pan.y }; panPos.current = { x: pan.x, y: pan.y }; setPanning(true); } }}
          onMouseMove={(e) => {
            if (!panRef.current) return;
            const nx = panRef.current.ox + (e.clientX - panRef.current.sx);
            const ny = panRef.current.oy + (e.clientY - panRef.current.sy);
            panPos.current = { x: nx, y: ny };
            // Aplica el pan directo al DOM: no dispara re-render por cada pixel.
            if (imgRef.current) imgRef.current.style.transform = `translate(${nx}px,${ny}px) scale(${zoom}) rotate(${rot}deg)`;
          }}
          onMouseUp={() => { if (panRef.current) { panRef.current = null; setPanning(false); setPan(panPos.current); } }}
          onMouseLeave={() => { if (panRef.current) { panRef.current = null; setPanning(false); setPan(panPos.current); } }}
          style={{ cursor: viewer?.src ? (panning ? "grabbing" : "grab") : "default" }}>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-white/[0.06] to-transparent" />
          {viewer?.src ? (
            <img ref={imgRef} src={viewer.src} alt={viewer.name} draggable={false}
              style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom}) rotate(${rot}deg)`, transition: panning ? "none" : "transform 0.18s var(--ease-out)", willChange: "transform" }}
              className="relative max-h-80 max-w-full object-contain select-none" />
          ) : viewer?.loading ? (
            <div className="relative flex flex-col items-center gap-2 text-slate-400">
              <span className="w-6 h-6 rounded-full border-2 border-white/15 border-t-fuchsia-400 animate-spin" />
              <span className="text-xs">Cargando imagen…</span>
            </div>
          ) : viewer ? (
            <div className="relative text-slate-500 text-center px-4">{viewer.name}<br /><span className="text-xs">{viewer.err || "Sin previsualización (RAW u otro formato)"}</span></div>
          ) : (
            <div className="relative text-center text-slate-600"><div className="text-2xl font-semibold tracking-wide text-slate-500">VISOR DE IMÁGENES</div><div className="mt-2 text-slate-500">Selecciona una imagen del explorador</div></div>
          )}
        </div>
        <div className="flex gap-2 -mt-1 justify-center">
          <IconBtn big title="Acercar" onClick={() => setZoom((z) => Math.min(5, z + 0.2))}><Icon name="zoomIn" className="w-[18px] h-[18px]" /></IconBtn>
          <IconBtn big title="Alejar" onClick={() => setZoom((z) => Math.max(0.2, z - 0.2))}><Icon name="zoomOut" className="w-[18px] h-[18px]" /></IconBtn>
          <IconBtn big title="Mover" onClick={() => { setZoom(1); setRot(0); setPan({ x: 0, y: 0 }); }}><Icon name="hand" className="w-[18px] h-[18px]" /></IconBtn>
          <IconBtn big title="Rotar 90°" onClick={() => setRot((r) => r + 90)}><Icon name="rotate" className="w-[18px] h-[18px]" /></IconBtn>
        </div>

        <h3 className="text-[15px] font-semibold text-slate-200 mt-1">Acciones rápidas</h3>
        <div className="grid grid-cols-3 gap-4">
          {CARDS.map((c, i) => (
            <button key={c.key} onClick={() => setModal(c.key)} style={{ "--i": i }}
              className="u-rise text-left rounded-2xl border border-white/10 bg-white/[0.045] backdrop-blur-md p-4 transition duration-200 hover:-translate-y-0.5 hover:border-fuchsia-500/40 hover:bg-white/[0.07] hover:shadow-[0_18px_40px_rgba(168,85,247,0.18)] shadow-[0_10px_30px_rgba(0,0,0,0.25)] active:scale-[0.98]">
              <img src={c.img} alt="" className="w-11 h-11 object-contain mb-2.5" />
              <div className="text-[14.5px] font-semibold">{c.title}</div>
              <div className="text-xs text-slate-400 mt-1">{c.desc}</div>
            </button>
          ))}
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.045] backdrop-blur p-4 flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-full ${proceso.running ? "bg-amber-400 animate-pulse" : "bg-slate-600"}`} />
          <span className="text-sm text-slate-300 flex-1 truncate">{proceso.mensaje}</span>
          <div className="w-48 h-1.5 rounded-full bg-white/[0.08] overflow-hidden">
            <div className={`h-full ${proceso.running ? "bg-gradient-to-r from-indigo-500 to-fuchsia-500 animate-pulse w-1/3" : "bg-gradient-to-r from-indigo-500 to-fuchsia-500"}`} style={proceso.running ? {} : { width: `${proceso.frac * 100}%` }} />
          </div>
        </div>
      </div>

      <Splitter onDown={(e) => startSplit("right", e)} />

      {/* DERECHA: Asistente IA */}
      <div style={{ width: rightW }} className={`shrink-0 min-h-0 flex flex-col ${CARD}`}>
        <ChatPanel roots={roots} user={user} />
      </div>

      {/* Modales */}
      {modal === "excel" && <CrearExcelModal roots={roots} onClose={() => setModal(null)} onDone={() => reloadOpen()} />}
      {modal === "carpetas" && <CrearCarpetasModal roots={roots} onClose={() => setModal(null)} onDone={() => reloadOpen()} />}
      {modal === "clasificar" && <ClasificarModal roots={roots} onClose={() => setModal(null)} onClassify={runClassify} />}

      <ClassifyProgress
        open={!!classify}
        frac={proceso.frac}
        stage={proceso.stage}
        folder={classify?.folder}
        names={classify?.names || []}
        photoPaths={classify?.photos || []}
        done={classify?.done}
        cancelling={classify?.cancelling}
        onCancel={cancelClassify}
        onClose={() => { setClassify(null); reloadOpen(...(roots || [])); }}
      />

      <ClassifyResults
        open={!!results}
        stats={results?.stats || {}}
        folders={results?.folders || []}
        onVerCarpetas={() => { if (results?.destino) call("open_path", { path: results.destino }).catch(() => {}); }}
        onClose={() => setResults(null)}
      />



      {/* Menú contextual (glass compacto) */}
      {ctx && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setCtx(null)} onContextMenu={(e) => { e.preventDefault(); setCtx(null); }} />
          <div className="u-pop origin-top-left fixed z-50 rounded-xl border border-white/10 bg-[#0d0f1a]/95 backdrop-blur-xl shadow-2xl py-1.5 min-w-[186px] text-[13px]" style={{ left: ctx.x, top: ctx.y }}>
            {ctx.isDir && <MenuItem icon="folderPlus" onClick={ctxNueva}>Nueva carpeta</MenuItem>}
            {ctx.isDir && <MenuItem icon="fileePlus" onClick={ctxAgregar}>Agregar archivos</MenuItem>}
            {!ctx.isRoot && <MenuItem icon="edit" onClick={ctxRenombrar}>Renombrar</MenuItem>}
            <MenuItem icon="folderOpen" onClick={() => { call("open_path", { path: ctx.isDir ? ctx.path : ctx.parent }).catch(() => {}); setCtx(null); }}>Abrir en explorador</MenuItem>
            <MenuItem icon="refresh" onClick={() => { reloadOpen(ctx.isDir ? ctx.path : ctx.parent); setCtx(null); }}>Refrescar</MenuItem>
            <div className="h-px bg-white/10 my-1 mx-2" />
            <MenuItem icon={ctx.isRoot ? "folder" : "trash"} danger={!ctx.isRoot} onClick={ctxEliminar}>{ctx.isRoot ? "Quitar del workspace" : "Eliminar"}</MenuItem>
          </div>
        </>
      )}

      <AppDialog dlg={dlg} setDlg={setDlg} />
    </div>
  );
}

function AppDialog({ dlg, setDlg }) {
  const [val, setVal] = useState("");
  useEffect(() => { setVal(dlg?.value || ""); }, [dlg]);
  if (!dlg) return null;
  const close = () => setDlg(null);
  const ok = () => { const v = val; close(); dlg.onOk?.(v); };
  return (
    <div className="u-overlay fixed inset-0 z-[60] flex items-center justify-center bg-black/55 backdrop-blur-sm" onMouseDown={close}>
      <div onMouseDown={(e) => e.stopPropagation()} className="u-sheet w-[380px] rounded-2xl border border-white/10 bg-[#0d0f1a]/95 backdrop-blur-xl shadow-2xl p-5">
        <div className="h-1 w-12 rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500 mb-3" />
        <h3 className="text-[15px] font-semibold">{dlg.title}</h3>
        <p className="text-xs text-slate-400 mt-1 mb-3">{dlg.label}</p>
        {dlg.prompt && (
          <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") ok(); if (e.key === "Escape") close(); }}
            placeholder={dlg.placeholder || ""}
            className="w-full h-10 px-3 rounded-xl bg-white/[0.05] border border-white/10 text-sm text-slate-100 placeholder:text-slate-500 focus:border-fuchsia-500/50 focus:outline-none mb-4" />
        )}
        <div className="flex justify-end gap-2">
          <button onClick={close} className="px-4 py-2 rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] text-sm font-medium">Cancelar</button>
          <button onClick={ok} className={`px-4 py-2 rounded-xl text-white text-sm font-semibold ${dlg.danger ? "bg-red-600 hover:bg-red-500" : "bg-gradient-to-br from-indigo-500 to-fuchsia-500 hover:brightness-110"}`}>{dlg.confirmText}</button>
        </div>
      </div>
    </div>
  );
}

const Tbtn = ({ img, onClick, title }) => (
  <button onClick={onClick} title={title}
    className="w-8 h-8 rounded-md hover:bg-white/[0.06] active:bg-white/[0.16] active:scale-90 flex items-center justify-center transition duration-100">
    <img src={img} alt="" className="w-[18px] h-[18px] object-contain" />
  </button>
);

const IconBtn = ({ children, onClick, title, big }) => (
  <button onClick={onClick} title={title}
    className={`${big ? "w-10 h-9" : "w-8 h-8"} rounded-lg bg-white/[0.06] border border-white/10 hover:bg-white/[0.12] active:bg-white/[0.2] active:scale-90 text-slate-300 text-sm flex items-center justify-center backdrop-blur transition duration-100`}>
    {children}
  </button>
);

function MenuItem({ children, onClick, danger, icon }) {
  return (
    <button onClick={onClick} className={`w-full flex items-center gap-2.5 text-left px-3 py-[7px] hover:bg-white/[0.07] ${danger ? "text-red-400" : "text-slate-200"}`}>
      {icon && <Icon name={icon} className="w-[15px] h-[15px] opacity-80" />}
      {children}
    </button>
  );
}

const ROW_H = 28; // alto de fila (= h-7); fijo para virtualizar

// Aplana el árbol VISIBLE (solo las carpetas abiertas aportan hijos) a una lista
// plana. Requisito para virtualizar: en vez de montar miles de nodos anidados,
// renderizamos una ventana de filas sobre un array.
function flattenTree(roots, tree) {
  const rows = [];
  const walk = (path, label, depth, isRoot) => {
    const node = tree[path];
    const open = !!node && !node.error;
    rows.push({ kind: "dir", path, label, depth, open, isRoot });
    if (open) {
      (node.dirs || []).forEach((d) => walk(`${path}/${d}`, d, depth + 1, false));
      (node.files || []).forEach((f) =>
        rows.push({ kind: "file", path: `${path}/${f}`, name: f, parent: path, depth: depth + 1 }));
    } else if (node?.error) {
      rows.push({ kind: "error", path, depth: depth + 1, error: node.error });
    }
  };
  (roots || []).forEach((r) => walk(r, r.split(/[\\/]/).filter(Boolean).pop() || r, 0, true));
  return rows;
}

// Explorador virtualizado: solo monta las filas visibles (+ overscan). Soporta
// decenas de miles de archivos sin trabar. El árbol aplanado se recalcula solo
// cuando cambian las raíces o el contenido cargado.
const FileTree = memo(function FileTree({ roots, tree, toggle, openFile, onContext }) {
  const rows = useMemo(() => flattenTree(roots, tree), [roots, tree]);
  const ref = useRef(null);
  const rafRef = useRef(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [vh, setVh] = useState(480);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setVh(el.clientHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => { ro.disconnect(); if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, []);

  // Coalesce el scroll a 1 re-render por frame (scroll fluido con miles de filas).
  const onScroll = () => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      if (ref.current) setScrollTop(ref.current.scrollTop);
    });
  };

  const total = rows.length;
  const overscan = 10;
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - overscan);
  const end = Math.min(total, Math.ceil((scrollTop + vh) / ROW_H) + overscan);
  const visible = rows.slice(start, end);

  return (
    <div ref={ref} onScroll={onScroll}
      className="flex-1 overflow-auto px-1.5 pb-3">
      {total === 0 ? (
        <p className="text-xs text-slate-500 p-3 text-center">Clic en "＋ Nueva carpeta / archivo" para comenzar</p>
      ) : (
        <div style={{ height: total * ROW_H, position: "relative" }}>
          {visible.map((row, i) => (
            <TreeRow key={`${row.kind}:${row.path}`} row={row} top={(start + i) * ROW_H}
              toggle={toggle} openFile={openFile} onContext={onContext} />
          ))}
        </div>
      )}
    </div>
  );
});

function TreeRow({ row, top, toggle, openFile, onContext }) {
  const pad = row.depth * 16 + 8;
  const rowStyle = {
    top,
    paddingLeft: pad,
    gridTemplateColumns: "16px 18px minmax(0, 1fr)",
    columnGap: "6px",
  };
  const common = "absolute left-0 right-0 grid items-center h-7 pr-2 rounded-lg transition-colors text-[13.5px]";
  if (row.kind === "error") {
    return <div style={{ top, paddingLeft: pad }} className="absolute left-0 right-0 h-7 flex items-center text-xs text-red-400 truncate pr-2">{row.error}</div>;
  }
  if (row.kind === "file") {
    return (
      <div style={rowStyle} onClick={() => openFile(row.parent, row.name)} onContextMenu={(e) => onContext(e, row.path, false)}
        className={`${common} cursor-pointer text-slate-400 hover:text-slate-100 hover:bg-white/[0.05]`}>
        <span aria-hidden="true" />
        <span className="flex h-[18px] w-[18px] items-center justify-center text-slate-400">
          <Icon name={isImage(row.name) ? "photo" : "file"} className="h-4 w-4" />
        </span>
        <span className="min-w-0 truncate leading-5">{row.name}</span>
      </div>
    );
  }
  return (
    <div style={rowStyle} onClick={() => toggle(row.path)} onContextMenu={(e) => onContext(e, row.path, true)}
      className={`${common} cursor-pointer text-slate-200 hover:bg-white/[0.05]`}>
      <span className="flex h-4 w-4 items-center justify-center">
        <Icon name="chevronDown"
          className={`h-3.5 w-3.5 transition-transform duration-200 ${row.open ? "text-fuchsia-300" : "-rotate-90 text-slate-400"}`} />
      </span>
      <span className="flex h-[18px] w-[18px] items-center justify-center text-amber-300/90">
        <Icon name={row.open ? "folderOpen" : "folder"} className="h-[17px] w-[17px]" />
      </span>
      <span className="min-w-0 truncate leading-5">{row.label}</span>
    </div>
  );
}
