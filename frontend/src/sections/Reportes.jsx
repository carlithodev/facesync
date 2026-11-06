import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { call, onReady, isEngineReady } from "../lib/sidecar";
import { save } from "@tauri-apps/plugin-dialog";
import Icon from "../components/Icon";
import reportFormats from "../assets/workspace/report-formats.png";

const PAGE = 8;

export default function Reportes({ user, active }) {
  const [ready, setReady] = useState(isEngineReady());
  const [reports, setReports] = useState([]);
  const [fTipo, setFTipo] = useState("Todos");
  const [fFecha, setFFecha] = useState("Todas");
  const [fCarpeta, setFCarpeta] = useState("Todas");
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setRefreshing(true);
    setMsg("");
    try {
      const data = await call("reports_list", { email: user?.email_safe });
      setReports(data.reports || []);
    } catch (error) {
      setMsg(String(error?.message || error));
    } finally {
      setRefreshing(false);
    }
  }, [user?.email_safe]);

  useEffect(() => onReady(() => setReady(true)), []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  useEffect(() => { if (active && ready) load(); }, [active, ready, load]);

  const cutoff = () => {
    const now = Date.now() / 1000;
    if (fFecha === "Hoy") {
      const date = new Date();
      date.setHours(0, 0, 0, 0);
      return date.getTime() / 1000;
    }
    if (fFecha === "7 días") return now - 7 * 86400;
    if (fFecha === "30 días") return now - 30 * 86400;
    return 0;
  };

  const folders = ["Todas", ...Array.from(new Set(reports.map((report) => report.carpeta).filter(Boolean)))];
  const filtered = reports.filter(
    (report) => (fTipo === "Todos" || report.tipo === fTipo)
      && (fCarpeta === "Todas" || report.carpeta === fCarpeta)
      && (report.ts || 0) >= cutoff(),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const pageItems = filtered.slice(page * PAGE, page * PAGE + PAGE);

  useEffect(() => { setPage(0); }, [fTipo, fFecha, fCarpeta]);
  useEffect(() => { if (page >= pages) setPage(Math.max(0, pages - 1)); }, [page, pages]);

  const select = async (report) => {
    if (sel?.path === report.path) {
      setSel(null);
      setDetail(null);
      return;
    }
    setSel(report);
    setDetail(null);
    try {
      setDetail(await call("report_detail", { path: report.path }));
    } catch {
      setDetail({});
    }
  };

  const view = (report) => call("open_path", { path: report.path }).catch((error) => setMsg(String(error?.message || error)));

  const download = async (report) => {
    try {
      const destination = await save({ defaultPath: report.nombre });
      if (!destination) return;
      await call("file_copy", { src: report.path, dest: destination });
      setMsg(`Guardado: ${destination}`);
    } catch (error) {
      setMsg(String(error?.message || error));
    }
  };

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <header className="flex items-center gap-3 border-b border-white/10 px-6 py-4 pr-32">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-400/15 bg-indigo-500/10 text-fuchsia-300">
          <Icon name="chart" className="h-[18px] w-[18px]" />
        </span>
        <div>
          <h1 className="text-xl font-bold tracking-tight">Reportes</h1>
          <p className="text-sm text-slate-400">Resultados y archivos generados por FaceSync.</p>
        </div>
      </header>

      <div className="relative flex-1 overflow-auto px-6 py-5">
        <div className="pointer-events-none absolute left-1/2 top-2 h-[250px] w-[470px] -translate-x-1/2 rounded-full bg-indigo-600/[0.025] blur-[100px]" />

        <section className="relative mx-auto flex max-w-[900px] flex-col items-center text-center">
          <div className="flex h-[96px] w-[300px] items-center justify-center overflow-hidden">
            <img
              src={reportFormats}
              alt="Reportes JSON, TXT y XLSX"
              className="h-full w-full object-contain opacity-90 mix-blend-lighten"
            />
          </div>
          <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-white">Consulta, filtra y exporta los resultados del motor</h2>
          <p className="mt-2 max-w-[520px] text-sm leading-5 text-slate-400">
            Revisa cada clasificación y descarga sus reportes en el formato que necesites.
          </p>
        </section>

        <section className="relative mx-auto mt-5 max-w-[900px] pb-5">
          <div className="mb-3 flex items-center gap-2">
            <FilterSelect className="w-[145px]" value={fFecha} onChange={setFFecha} opts={["Todas", "Hoy", "7 días", "30 días"]} />
            <FilterSelect className="w-[145px]" value={fTipo} onChange={setFTipo} opts={["Todos", "Excel", "JSON", "TXT", "CSV"]} />
            <FilterSelect className="min-w-0 flex-1" value={fCarpeta} onChange={setFCarpeta} opts={folders} />
            <button
              type="button"
              onClick={load}
              disabled={refreshing}
              title="Refrescar reportes"
              aria-label="Refrescar reportes"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-400 transition hover:bg-white/[0.07] hover:text-white active:scale-[0.95] disabled:opacity-50"
            >
              <Icon name="refresh" className={`h-[17px] w-[17px] ${refreshing ? "animate-spin" : ""}`} />
            </button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.025] shadow-[0_18px_50px_rgba(0,0,0,0.18)] backdrop-blur-xl">
            {pageItems.length === 0 ? (
              <div className="py-12 text-center text-sm text-slate-500">
                Aún no hay reportes.<br />
                <span className="text-xs">Se generan automáticamente al clasificar fotografías.</span>
              </div>
            ) : (
              <div className="flex flex-col divide-y divide-white/[0.06]">
                {pageItems.map((report, index) => {
                  const selected = sel?.path === report.path;
                  return (
                    <div key={report.path} style={{ "--i": index }} className="u-rise">
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => select(report)}
                        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") select(report); }}
                        className={`flex cursor-pointer items-center gap-3.5 px-5 py-3.5 text-left transition ${selected ? "bg-indigo-500/[0.08]" : "hover:bg-white/[0.035]"}`}
                      >
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.045] text-slate-300">
                          <Icon name="file" className="h-[18px] w-[18px]" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-slate-100">{report.nombre}</div>
                          <div className="mt-0.5 truncate text-xs text-slate-500">{report.tipo} · {report.carpeta} · {report.fecha}</div>
                        </div>
                        <span className="hidden shrink-0 rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-2.5 py-1 text-[11px] font-medium text-emerald-300 sm:block">
                          {report.estado}
                        </span>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <button
                            type="button"
                            title="Ver reporte"
                            aria-label={`Ver ${report.nombre}`}
                            onClick={(event) => { event.stopPropagation(); view(report); }}
                            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 transition hover:bg-white/[0.07] hover:text-indigo-200 active:scale-[0.95]"
                          >
                            <Icon name="eye" className="h-[17px] w-[17px]" />
                          </button>
                          <button
                            type="button"
                            title="Descargar reporte"
                            aria-label={`Descargar ${report.nombre}`}
                            onClick={(event) => { event.stopPropagation(); download(report); }}
                            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 transition hover:bg-white/[0.07] hover:text-fuchsia-200 active:scale-[0.95]"
                          >
                            <Icon name="download" className="h-[17px] w-[17px]" />
                          </button>
                        </div>
                      </div>

                      {selected && (
                        <div className="u-expand grid grid-cols-5 gap-3 border-t border-white/[0.05] bg-black/[0.09] px-5 py-3 text-xs">
                          <Detail label="Origen" value={detail?.origen} />
                          <Detail label="Destino" value={detail?.destino} />
                          <Detail label="Analizadas" value={detail?.analizadas} />
                          <Detail label="Clasificadas" value={detail?.clasificadas} />
                          <Detail label="Pendientes" value={detail?.pendientes} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {filtered.length > PAGE && (
            <div className="mt-3 flex items-center justify-end gap-2 text-xs text-slate-400">
              <button type="button" onClick={() => setPage((current) => Math.max(0, current - 1))} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] transition hover:bg-white/[0.08]">‹</button>
              <span>{page + 1}/{pages}</span>
              <button type="button" onClick={() => setPage((current) => Math.min(pages - 1, current + 1))} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] transition hover:bg-white/[0.08]">›</button>
            </div>
          )}

          {msg && <div className="mt-3 truncate text-xs text-slate-500">{msg}</div>}
        </section>
      </div>
    </div>
  );
}

const Detail = ({ label, value }) => (
  <div className="min-w-0">
    <div className="text-[10px] uppercase tracking-wider text-slate-600">{label}</div>
    <div className="mt-1 truncate text-slate-300">{value ?? "—"}</div>
  </div>
);

function FilterSelect({ value, onChange, opts, className = "" }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState(null);
  const buttonRef = useRef(null);

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const bounds = buttonRef.current?.getBoundingClientRect();
    if (!bounds) return;
    setPosition({
      left: bounds.left,
      top: bounds.bottom + 6,
      width: bounds.width,
      maxHeight: Math.max(140, window.innerHeight - bounds.bottom - 16),
    });
    setOpen(true);
  };

  return (
    <div className={className}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={toggle}
        className={`flex h-11 w-full items-center justify-between gap-2 rounded-xl border bg-white/[0.04] px-3.5 text-sm text-slate-100 transition hover:bg-white/[0.06] focus:outline-none ${open ? "border-fuchsia-500/50 bg-white/[0.06]" : "border-white/10"}`}
      >
        <span className="truncate text-left">{value}</span>
        <Icon name="chevronDown" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>

      {open && position && createPortal(
        <>
          <div className="fixed inset-0 z-[55]" onMouseDown={() => setOpen(false)} />
          <div
            role="listbox"
            className="u-pop fixed z-[56] overflow-auto rounded-xl border border-white/10 bg-[#11131f]/98 p-1.5 shadow-2xl backdrop-blur-xl"
            style={{ left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight }}
          >
            {opts.map((option) => (
              <div
                key={option}
                role="option"
                aria-selected={option === value}
                onMouseDown={() => { onChange(option); setOpen(false); }}
                className={`mb-0.5 flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm transition last:mb-0 ${option === value ? "bg-indigo-500/20 text-white" : "text-slate-200 hover:bg-white/[0.06]"}`}
              >
                <span className="truncate">{option}</span>
                {option === value && <Icon name="check" className="h-4 w-4 shrink-0 text-fuchsia-300" />}
              </div>
            ))}
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
