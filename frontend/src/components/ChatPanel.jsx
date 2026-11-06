import { memo, useEffect, useRef, useState } from "react";
import { call, onReady, isEngineReady } from "../lib/sidecar";
import agent from "../assets/workspace/agent.png";

// Panel de chat del asistente IA. Stream vía chat_send: cada mensaje
// (Sistema/Asistente) llega como progress {kind:'msg',role,text}; el progreso
// del motor (si se clasifica desde el chat) como {kind:'motor',data}.

const WELCOME = { role: "Asistente", text: "Hola 👋 Pídeme leer tu Excel, crear carpetas, clasificar fotos u organizar tu workspace." };

function ChatPanel({ roots, user }) {
  const [msgs, setMsgs] = useState([WELCOME]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [motorStatus, setMotorStatus] = useState(null);
  const [ready, setReady] = useState(isEngineReady());
  const listRef = useRef(null);
  const textRef = useRef(null);
  const email = user?.email_safe || user?.email || "";
  const rootsKey = JSON.stringify(roots || []);

  useEffect(() => onReady(() => setReady(true)), []);

  useEffect(() => {
    if (!ready || !email) return;
    let active = true;
    setBootstrapping(true);
    call("chat_bootstrap", { email, roots: JSON.parse(rootsKey) })
      .then((data) => {
        if (!active) return;
        const history = Array.isArray(data?.history) ? data.history : [];
        setMsgs(history.length ? history : [WELCOME]);
      })
      .catch((error) => {
        if (!active) return;
        setMsgs([WELCOME, { role: "Sistema", text: String(error?.message || error) }]);
      })
      .finally(() => active && setBootstrapping(false));
    return () => { active = false; };
  }, [ready, email, rootsKey]);

  // Scroll SOLO del contenedor de mensajes (scrollTop), NUNCA scrollIntoView:
  // scrollIntoView mueve ancestros (incluido el root fixed con overflow-hidden)
  // y desplazaba toda la app hacia arriba.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs]);

  // El compositor crece con el contenido hasta 5 líneas; después conserva su
  // tamaño y desplaza únicamente el texto interno.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "0px";
    const nextHeight = Math.max(24, Math.min(el.scrollHeight, 112));
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > 112 ? "auto" : "hidden";
  }, [text]);

  const send = async (forced) => {
    const t = String(forced ?? text).trim();
    if (!t || busy || bootstrapping || !email) return;
    setMsgs((m) => [...m, { role: "Tú", text: t }]);
    setText("");
    setBusy(true);
    try {
      await call("chat_send", { text: t, roots: roots || [], email }, (p) => {
        if (p.kind === "msg") setMsgs((m) => [...m, { role: p.role, text: p.text }]);
        else if (p.kind === "motor") {
          const data = p.data || {};
          setMotorStatus({
            message: data.message || data.mensaje || "Procesando FaceSync…",
            percent: Number.isFinite(data.percent) ? data.percent : null,
            stage: data.stage || "",
          });
        }
      });
    } catch (e) {
      setMsgs((m) => [...m, { role: "Sistema", text: String(e.message || e) }]);
    } finally {
      setBusy(false);
      setMotorStatus(null);
    }
  };

  const cancelChat = async () => {
    if (!busy || !email) return;
    setMotorStatus((current) => ({ ...(current || {}), message: "Cancelando…" }));
    try { await call("chat_cancel", { email }); }
    catch (error) { setMsgs((m) => [...m, { role: "Sistema", text: String(error?.message || error) }]); }
  };

  const newConversation = async () => {
    if (busy || bootstrapping || !email) return;
    setBootstrapping(true);
    try {
      await call("chat_new", { email, roots: roots || [] });
      setMsgs([WELCOME]);
      setMotorStatus(null);
    } catch (error) {
      setMsgs((m) => [...m, { role: "Sistema", text: String(error?.message || error) }]);
    } finally {
      setBootstrapping(false);
    }
  };

  const statusText = busy ? "Procesando…" : bootstrapping ? "Recuperando memoria…" : ready ? "En línea" : "Conectando…";
  const statusColor = busy ? "text-fuchsia-300" : ready ? "text-emerald-400" : "text-amber-400";

  return (
    <div className="relative h-full flex flex-col overflow-hidden">
      {/* glow ambiental */}
      <div className="pointer-events-none absolute -top-24 -right-12 h-56 w-56 rounded-full bg-fuchsia-600/10 blur-[90px]" />
      <div className="pointer-events-none absolute bottom-20 -left-16 h-48 w-48 rounded-full bg-indigo-700/10 blur-[90px]" />

      {/* Header con identidad del asistente */}
      <div className="relative pl-4 pr-3 pt-10 pb-3 border-b border-white/[0.07] flex items-center gap-3">
        <div className={`relative shrink-0 rounded-full ${busy || !ready ? "avatar-live" : ""}`}>
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500/30 to-fuchsia-500/30 ring-1 ring-white/15 backdrop-blur flex items-center justify-center">
            <img src={agent} alt="" className="w-7 h-7 object-contain drop-shadow" />
          </div>
          <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-[#0b0c14] ${ready ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-bold text-slate-100 leading-tight">Asistente IA</h2>
          <span className={`text-[11px] flex items-center gap-1.5 ${statusColor}`}>
            {busy
              ? <span className="chat-typing inline-flex gap-1"><span /><span /><span /></span>
              : <span className={`w-1.5 h-1.5 rounded-full ${ready ? "bg-emerald-400" : "bg-amber-400"}`} />}
            {statusText}
          </span>
        </div>
      </div>

      {/* Conversación */}
      <div ref={listRef} className="relative flex-1 overflow-auto px-3 py-4 flex flex-col gap-3">
        {msgs.map((m, i) => <Bubble key={i} role={m.role} text={m.text} onPick={send} />)}
        {motorStatus && (
          <div className="mx-2 rounded-2xl border border-fuchsia-400/20 bg-fuchsia-500/[0.07] px-3 py-2.5">
            <div className="flex items-center gap-2 text-[12px] text-fuchsia-100">
              <span className="w-2 h-2 rounded-full bg-fuchsia-400 animate-pulse" />
              <span className="flex-1 truncate">{motorStatus.message}</span>
              {motorStatus.percent != null && <span>{Math.round(motorStatus.percent)}%</span>}
            </div>
            {motorStatus.percent != null && (
              <div className="mt-2 h-1 rounded-full bg-white/[0.08] overflow-hidden">
                <div className="h-full bg-gradient-to-r from-indigo-500 to-fuchsia-500 transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, motorStatus.percent))}%` }} />
              </div>
            )}
          </div>
        )}
        {busy && (
          <div className="msg-left flex items-end gap-2">
            <Avatar />
            <div className="rounded-2xl rounded-bl-md bg-white/[0.06] border border-white/10 px-4 py-3 text-slate-400">
              <span className="chat-typing inline-flex gap-1.5"><span /><span /><span /></span>
            </div>
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="relative p-3 border-t border-white/[0.07]">
        <div className="rounded-[20px] bg-white/[0.05] border border-white/10 px-3 py-2.5 transition focus-within:border-fuchsia-500/40 focus-within:bg-white/[0.07] focus-within:shadow-[0_0_0_3px_rgba(217,70,239,0.06)]">
          <textarea
            ref={textRef}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!busy) send();
              }
            }}
            disabled={bootstrapping}
            placeholder="Escribe un mensaje…"
            className="block min-h-6 w-full resize-none overflow-x-hidden whitespace-pre-wrap break-words bg-transparent px-0.5 text-sm leading-6 text-slate-100 placeholder:text-slate-500 focus:outline-none disabled:opacity-50"
          />
          <div className="mt-2 flex items-center justify-between">
            <button onClick={newConversation} disabled={busy || bootstrapping} title="Nueva conversación" aria-label="Nueva conversación"
              className="flex h-8 w-8 items-center justify-center rounded-xl text-slate-400 transition hover:bg-white/[0.08] hover:text-white active:scale-90 disabled:opacity-35 disabled:active:scale-100">
              <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
            </button>
            <button onClick={busy ? cancelChat : () => send()}
              disabled={bootstrapping || (!busy && !text.trim())}
              title={busy ? "Detener respuesta" : "Enviar"}
              aria-label={busy ? "Detener respuesta" : "Enviar"}
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white shadow-lg transition active:scale-90 disabled:opacity-40 disabled:active:scale-100 ${busy ? "bg-gradient-to-br from-rose-500 to-fuchsia-600 shadow-rose-900/30 hover:brightness-110" : "bg-gradient-to-br from-indigo-500 to-fuchsia-500 shadow-fuchsia-900/30 hover:brightness-110"}`}>
              {busy ? (
                <span className="h-2.5 w-2.5 rounded-[2px] bg-white" />
              ) : (
                <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              )}
            </button>
          </div>
        </div>
        <div className="text-[11px] text-slate-500 mt-2 text-center">IA puede cometer errores. Verifica resultados.</div>
      </div>
    </div>
  );
}

export default memo(ChatPanel);

// Avatar del asistente (line-art sobre disco glass)
function Avatar() {
  return (
    <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500/25 to-fuchsia-500/25 ring-1 ring-white/10 flex items-center justify-center self-end">
      <img src={agent} alt="" className="w-5 h-5 object-contain" />
    </div>
  );
}

// Burbuja por rol (mismos datos del chat; solo presentación)
function Bubble({ role, text, onPick }) {
  if (role === "Tú") {
    return (
      <div className="msg-right flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-indigo-500/90 to-fuchsia-500/90 text-white px-3.5 py-2 text-sm shadow-lg shadow-fuchsia-900/20 whitespace-pre-wrap break-words">
          {text}
        </div>
      </div>
    );
  }
  if (role === "Sistema") {
    return (
      <div className="msg-left flex justify-center">
        <div className="max-w-[92%] rounded-full bg-white/[0.05] border border-white/10 text-slate-400 px-3 py-1 text-[11px] text-center">
          {text}
        </div>
      </div>
    );
  }
  // Asistente: separa el cuerpo de las opciones de siguiente paso ([[OPC]]).
  const [body, optRaw] = String(text).split("[[OPC]]");
  const opts = optRaw ? optRaw.split("|").map((s) => s.trim()).filter(Boolean) : [];
  return (
    <div className="msg-left flex items-end gap-2">
      <Avatar />
      <div className="max-w-[85%]">
        <div className="text-[10px] text-slate-500 mb-0.5 ml-1">{role === "Asistente" ? "Asistente" : role}</div>
        <div className="rounded-2xl rounded-bl-md bg-white/[0.06] border border-white/10 text-slate-100 px-3.5 py-2 text-sm whitespace-pre-wrap break-words">
          {body.trim()}
        </div>
        {opts.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {opts.map((o) => (
              <button key={o} onClick={() => onPick?.(o)}
                className="group inline-flex items-center gap-1 rounded-full border border-fuchsia-400/30 bg-fuchsia-500/10 px-3 py-1 text-[12px] text-fuchsia-100 transition hover:bg-fuchsia-500/20 hover:border-fuchsia-400/50 active:scale-95">
                <span className="text-fuchsia-300/80 group-hover:translate-x-0.5 transition-transform">→</span>{o}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
