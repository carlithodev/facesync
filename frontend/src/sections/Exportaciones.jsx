import { useCallback, useEffect, useRef, useState } from "react";
import { call, cancel, onReady, isEngineReady } from "../lib/sidecar";
import { openDriveFolder } from "../lib/native";
import Icon from "../components/Icon";
import iconDrive from "../assets/workspace/drive.png";

const baseName = (path) => (path || "").split(/[\\/]/).filter(Boolean).pop() || path;

export default function Exportaciones({ user, roots = [], active }) {
  const [ready, setReady] = useState(isEngineReady());
  const [exports, setExports] = useState([]);
  const [picking, setPicking] = useState(false);
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [exportingPath, setExportingPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [historyMessage, setHistoryMessage] = useState("");
  const exportJob = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await call("exports_list", { email: user?.email_safe });
      setExports(data.exports || []);
    } catch {
      setExports([]);
    }
  }, [user?.email_safe]);

  useEffect(() => onReady(() => setReady(true)), []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  useEffect(() => { if (active && ready) load(); }, [active, ready, load]);

  const runExport = async (folder) => {
    setPicking(false);
    if (!folder) return;

    setExportingPath(folder);
    setBusy(true);
    setCancelling(false);
    setResult(null);
    setProgress({ estado: "running", mensaje: "Preparando exportación…", procesados: 0, total: 0, subidos: 0 });

    try {
      const summary = await call(
        "drive_export_start",
        { carpeta: folder, email: user?.email_safe },
        (data) => setProgress(data),
        (id) => { exportJob.current = id; },
      );
      setResult(summary);
      await load();
    } catch (error) {
      setResult({ ok: false, error: String(error?.message || error) });
    } finally {
      exportJob.current = null;
      setBusy(false);
      setCancelling(false);
    }
  };

  const cancelExport = () => {
    const id = exportJob.current;
    if (!id || cancelling) return;
    setCancelling(true);
    setProgress((current) => ({ ...current, mensaje: "Cancelando exportación…" }));
    cancel(id).catch(() => setCancelling(false));
  };

  const closeProgress = () => {
    if (busy) return;
    setProgress(null);
    setResult(null);
    setExportingPath("");
  };

  const goToDrive = async () => {
    const folderId = result?.drive_folder_id;
    if (!folderId) return;
    try {
      await openDriveFolder(folderId);
    } catch (error) {
      setResult((current) => ({ ...current, openError: String(error?.message || error) }));
    }
  };

  const startPicking = () => {
    if (!busy) setPicking(true);
  };

  const openHistoryItem = async (item) => {
    setHistoryMessage("");
    try {
      await openDriveFolder(item?.drive_folder_id || null);
    } catch (error) {
      setHistoryMessage(`No pude abrir Google Drive: ${String(error?.message || error)}`);
    }
  };

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <header className="flex items-center gap-3 border-b border-white/10 px-6 py-4 pr-32">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-400/15 bg-indigo-500/10 text-fuchsia-300">
          <Icon name="export" className="h-[18px] w-[18px]" />
        </span>
        <div>
          <h1 className="text-xl font-bold tracking-tight">Exportar a Drive</h1>
          <p className="text-sm text-slate-400">Respalda tus carpetas de forma segura en Google Drive.</p>
        </div>
      </header>

      <div className="relative flex-1 overflow-auto px-6 py-5">
        <div className="pointer-events-none absolute left-1/2 top-2 h-[260px] w-[460px] -translate-x-1/2 rounded-full bg-indigo-600/[0.025] blur-[100px]" />

        <section className="relative mx-auto flex max-w-[900px] flex-col items-center text-center">
          <div className="relative flex h-28 w-28 items-center justify-center">
            <div className="absolute inset-0 rounded-full border border-white/[0.06]" />
            <div className="relative flex h-[68px] w-[68px] items-center justify-center rounded-[22px] border border-white/[0.08] bg-white/[0.035] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-xl">
              <img src={iconDrive} alt="Google Drive" className="h-9 w-9 object-contain" />
            </div>
          </div>

          <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-white">Exporta tus carpetas clasificadas</h2>
          <p className="mt-2 max-w-[500px] text-sm leading-5 text-slate-400">
            Guarda tus carpetas clasificadas en la nube y accede desde cualquier lugar.
          </p>

          <button type="button" onClick={startPicking} disabled={busy}
            className="mt-5 flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.045] px-5 text-sm font-medium text-slate-100 transition hover:border-indigo-400/30 hover:bg-white/[0.07] active:scale-[0.97] disabled:opacity-50">
            <Icon name="export" className="h-4 w-4 text-indigo-300" />
            <span>{busy ? "Exportando…" : "Exportar a Drive"}</span>
          </button>
        </section>

        <section className="relative mx-auto mt-6 max-w-[820px] pb-5">
          {exports.length === 0 ? (
            <div className="flex items-center justify-center gap-2 text-xs text-slate-500">
              <span className="h-4 w-4 rounded-full border border-dashed border-slate-500/80" />
              Sin exportaciones todavía
            </div>
          ) : (
            <div className="u-fade overflow-hidden rounded-2xl border border-white/10 bg-white/[0.025] shadow-[0_18px_50px_rgba(0,0,0,0.18)] backdrop-blur-xl">
              <div className="border-b border-white/[0.07] px-5 py-4 text-left">
                <h3 className="text-sm font-semibold text-slate-200">Carpetas exportadas</h3>
                <p className="mt-0.5 text-xs text-slate-500">Historial de respaldos enviados a Google Drive.</p>
              </div>
              <div className="flex flex-col divide-y divide-white/[0.06]">
                {exports.map((item, index) => (
                  <div key={`${item.nombre}-${item.ts || item.fecha || index}`} style={{ "--i": index }}
                    className="u-rise flex items-center gap-3.5 px-5 py-3.5 text-left transition hover:bg-white/[0.035]">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.045]">
                      <img src={iconDrive} alt="" className="h-5 w-5 object-contain" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-100">{item.nombre}</div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">{baseName(item.origen) || "Google Drive"} · {item.fecha || "Sin fecha"}</div>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium ${item.estado === "Completado" ? "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300" : "border-amber-400/20 bg-amber-400/[0.07] text-amber-300"}`}>
                      {item.estado || "Registrada"}
                    </span>
                    {item.estado === "Completado" && (
                      <button
                        type="button"
                        onClick={() => openHistoryItem(item)}
                        className="flex h-9 shrink-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 text-xs font-medium text-slate-300 transition hover:border-indigo-400/25 hover:bg-white/[0.07] hover:text-white active:scale-[0.97]"
                      >
                        <img src={iconDrive} alt="" className="h-3.5 w-3.5 object-contain" />
                        Ir a Drive
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {historyMessage && <div className="mt-3 text-center text-xs text-red-300">{historyMessage}</div>}
        </section>
      </div>

      {picking && <ExportPicker roots={roots} onPick={runExport} onClose={() => setPicking(false)} />}
      {(progress || result) && (
        <DriveProgressModal
          path={exportingPath}
          progress={progress}
          result={result}
          busy={busy}
          cancelling={cancelling}
          onCancel={cancelExport}
          onDone={closeProgress}
          onOpenDrive={goToDrive}
        />
      )}
    </div>
  );
}

function DriveProgressModal({ path, progress, result, busy, cancelling, onCancel, onDone, onOpenDrive }) {
  const total = Number(progress?.total) || Number(result?.total) || 0;
  const processed = Number(progress?.procesados) || (result ? total : 0);
  const uploaded = Number(progress?.subidos) || Number(result?.subidos) || 0;
  const percent = result && !result.error ? 100 : total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const completed = !busy && Boolean(result);
  const canceled = Boolean(result?.canceled);
  const failed = Boolean(result?.error);
  const partial = completed && !canceled && !failed && !result?.ok;

  const title = busy
    ? "Exportando a Drive"
    : canceled
      ? "Exportación cancelada"
      : failed
        ? "No se pudo exportar"
        : partial
          ? "Exportación parcial"
          : "Exportación completada";

  const status = busy
    ? (progress?.mensaje || "Subiendo archivos…")
    : canceled
      ? `Se subieron ${result?.subidos || 0} de ${result?.total || 0} archivos antes de cancelar.`
      : failed
        ? result.error
        : partial
          ? `Se subieron ${result?.subidos || 0} de ${result?.total || 0} archivos.`
          : `${result?.subidos || 0} archivos se guardaron correctamente.`;

  return (
    <div className="u-overlay fixed inset-0 z-[90] flex items-center justify-center bg-black/65 p-6 backdrop-blur-md">
      <div className="u-sheet relative w-full max-w-[500px] overflow-hidden rounded-3xl border border-white/10 bg-[#0b0c14]/95 shadow-[0_30px_90px_rgba(0,0,0,0.68)] backdrop-blur-2xl">
        <div className="pointer-events-none absolute -right-16 -top-20 h-44 w-44 rounded-full bg-fuchsia-600/10 blur-[70px]" />
        <div className="relative flex items-start gap-3.5 px-7 pb-4 pt-6">
          <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border ${completed && !failed && !partial ? "border-emerald-400/20 bg-emerald-400/10" : "border-white/10 bg-white/[0.05]"}`}>
            {completed && !failed && !partial
              ? <Icon name="check" className="h-5 w-5 text-emerald-300" />
              : <img src={iconDrive} alt="" className="h-6 w-6 object-contain" />}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[18px] font-bold tracking-tight text-white">{title}</h2>
            <p className="mt-1 truncate text-[13px] text-slate-400">Carpeta: <span className="text-slate-300">{baseName(path)}</span></p>
          </div>
        </div>

        <div className="relative px-7 pb-6 pt-2">
          <div className={`rounded-2xl border p-4 ${failed ? "border-red-400/20 bg-red-400/[0.06]" : partial ? "border-amber-400/20 bg-amber-400/[0.06]" : "border-white/[0.08] bg-white/[0.025]"}`}>
            <p className={`min-h-5 text-sm ${failed ? "text-red-200" : partial ? "text-amber-200" : "text-slate-300"}`}>{status}</p>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.07]">
              {total > 0 || completed ? (
                <div className={`h-full rounded-full transition-[width] duration-500 ease-out ${failed || canceled || partial ? "bg-gradient-to-r from-indigo-500 to-fuchsia-500" : "bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500"}`}
                  style={{ width: `${percent}%` }} />
              ) : (
                <div className="h-full w-1/3 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500" />
              )}
            </div>

            <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
              <span>{total > 0 ? `${uploaded} de ${total} archivos` : "Preparando archivos…"}</span>
              <span>{total > 0 || completed ? `${percent}%` : ""}</span>
            </div>
          </div>

          {result?.openError && (
            <div className="mt-3 rounded-xl border border-red-400/20 bg-red-400/[0.07] px-3 py-2 text-xs text-red-200">{result.openError}</div>
          )}
        </div>

        <div className="relative flex min-h-[73px] items-center justify-between border-t border-white/[0.06] px-7 py-4">
          {completed && result?.drive_folder_id && !failed && !canceled ? (
            <button type="button" onClick={onOpenDrive}
              className="flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] active:scale-[0.97]">
              <img src={iconDrive} alt="" className="h-4 w-4 object-contain" />
              Ir a Drive
            </button>
          ) : <span />}

          {busy ? (
            <button type="button" onClick={onCancel} disabled={cancelling}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:border-red-400/25 hover:bg-red-400/[0.07] hover:text-red-200 active:scale-[0.97] disabled:opacity-50">
              {cancelling ? "Cancelando…" : "Cancelar"}
            </button>
          ) : (
            <button type="button" onClick={onDone}
              className="rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-900/30 transition hover:brightness-110 active:scale-[0.97]">
              Listo
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ExportPicker({ roots = [], onPick, onClose }) {
  const [path, setPath] = useState(null);
  const [dirs, setDirs] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const openFolder = async (nextPath) => {
    setPath(nextPath);
    setLoading(true);
    try {
      const data = await call("fs_list_dir", { path: nextPath });
      setDirs(data.dirs || []);
    } catch {
      setDirs([]);
    } finally {
      setLoading(false);
    }
  };

  const goRoots = () => { setPath(null); setDirs([]); };
  const goUp = () => {
    if (!path) return;
    if (roots.includes(path)) { goRoots(); return; }
    const parent = path.replace(/[\\/]+[^\\/]+$/, "");
    if (!parent || parent === path) goRoots();
    else openFolder(parent);
  };

  const items = path ? dirs.map((dir) => `${path}/${dir}`) : roots;

  return (
    <div className="u-overlay fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-6 backdrop-blur-md">
      <div className="u-sheet relative flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#0b0c14]/95 shadow-[0_30px_90px_rgba(0,0,0,0.65)] backdrop-blur-2xl">
        <div className="pointer-events-none absolute -top-20 left-1/2 h-40 w-72 -translate-x-1/2 rounded-full bg-indigo-600/12 blur-[80px]" />
        <button type="button" onClick={onClose} aria-label="Cancelar exportación"
          className="absolute right-5 top-5 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-lg leading-none text-slate-400 shadow-lg shadow-black/20 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white active:scale-95">
          ×
        </button>

        <div className="relative px-7 pb-3 pr-16 pt-7">
          <h2 className="text-[18px] font-semibold tracking-tight">Elige una carpeta para exportar</h2>
          <p className="mt-1 text-[13px] text-slate-400">Selecciona del workspace lo que quieres respaldar en Drive.</p>
        </div>

        <div className="relative flex items-center gap-1.5 px-7 pb-2 text-xs">
          <button type="button" onClick={goRoots} disabled={!path}
            className="rounded-md px-2 py-1 text-slate-300 transition hover:bg-white/[0.06] disabled:opacity-40">Workspace</button>
          {path && (
            <>
              <span className="text-slate-600">/</span>
              <span className="truncate text-slate-200">{baseName(path)}</span>
              <button type="button" onClick={goUp} className="ml-auto rounded-md px-2 py-1 text-slate-400 transition hover:bg-white/[0.06]">↑ Subir</button>
            </>
          )}
        </div>

        <div className="relative min-h-0 flex-1 overflow-auto px-4 py-2">
          {loading ? (
            <div className="py-12 text-center text-sm text-slate-500">Cargando…</div>
          ) : items.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-500">{path ? "Esta carpeta no tiene subcarpetas." : "No hay carpetas en el workspace."}</div>
          ) : (
            <div className="flex flex-col gap-1">
              {items.map((itemPath) => (
                <button type="button" key={itemPath} onClick={() => openFolder(itemPath)}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-white/[0.06]">
                  <Icon name="folder" className="h-4 w-4 shrink-0 text-amber-300/80" />
                  <span className="truncate text-sm text-slate-200">{baseName(itemPath)}</span>
                  <span className="ml-auto text-slate-600">›</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="relative flex items-center justify-between gap-3 border-t border-white/[0.06] px-7 py-4">
          <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
            {path ? <>Exportar: <span className="text-slate-300">{baseName(path)}</span></> : "Entra a una carpeta para exportarla"}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] active:scale-[0.97]">Cancelar</button>
            <button type="button" onClick={() => path && onPick(path)} disabled={!path}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-900/30 transition hover:brightness-110 active:scale-[0.97] disabled:opacity-40">
              <img src={iconDrive} alt="" className="h-4 w-4 object-contain" />
              Exportar a Drive
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
