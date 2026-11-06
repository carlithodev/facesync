import { useEffect, useState } from "react";
import { call } from "../lib/sidecar";
import { readImageDataUrl } from "../lib/native";
import logo from "../assets/login/logoface.png";
import heroTablet from "../assets/login/loginassest.png";
import heroFace from "../assets/login/loginassest3.png";
import features from "../assets/login/loginassest2.png";
import iconGoogle from "../assets/login/google.png";

const LAST_ACCOUNT_KEY = "facesync:last-account";

// Login — diseño de FaceSync Studio (hero + gradiente + card glass) adaptado a
// los elementos de V2: cuentas guardadas + Google (sin email/password).
// La barra de título la pone App (TitleBar). Solo VISUAL: misma lógica OAuth.

function HeroColumn() {
  return (
    <section className="hidden flex-1 flex-col items-center justify-center gap-10 px-14 lg:flex">
      <img src={logo} alt="FaceSync" className="w-[280px]" />
      <div className="relative h-[280px] w-[440px]">
        <div className="absolute left-1/2 top-1/2 h-[180px] w-[360px] -translate-x-1/2 -translate-y-1/2 rounded-[50%] bg-fuchsia-600/25 blur-[70px]" />
        <div className="absolute left-1/2 top-1/2 h-[160px] w-[420px] -translate-x-1/2 -translate-y-1/2 rotate-[-6deg] rounded-[50%] border border-fuchsia-500/20" />
        <div className="absolute left-0 top-1/2 w-[320px] -translate-y-1/2">
          <img src={heroTablet} alt="" className="w-full drop-shadow-2xl [will-change:transform] animate-[floaty_5s_ease-in-out_infinite] motion-reduce:animate-none" />
        </div>
        <img src={heroFace} alt="" className="absolute bottom-1 right-3 w-[165px] drop-shadow-2xl [will-change:transform] animate-[floaty-soft_4.2s_ease-in-out_0.7s_infinite] motion-reduce:animate-none" />
      </div>
      <img src={features} alt="" className="w-[360px] max-w-full mx-auto" />
    </section>
  );
}

// Anillo girando sutil (estado "entrando"), tono neutro y discreto.
function Spinner({ className = "h-3.5 w-3.5" }) {
  return (
    <span className={`inline-block rounded-full border-[1.5px] border-white/15 border-t-white/70 animate-spin ${className}`} />
  );
}

function GoogleButton({ onClick, disabled, loading, children }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex w-full items-center justify-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] py-3 text-sm font-medium text-white transition hover:bg-white/[0.07] disabled:opacity-70">
      {loading ? <Spinner /> : <img src={iconGoogle} alt="" className="h-5 w-5" />}
      {children}
    </button>
  );
}

export default function Login({ onLogin }) {
  const [accounts, setAccounts] = useState(null);
  const [avatars, setAvatars] = useState({});
  const [busy, setBusy] = useState(false);
  const [entering, setEntering] = useState(null); // email_safe en curso, o "new"
  const [msg, setMsg] = useState("");

  useEffect(() => { refresh(); }, []);

  // Cuentas vía comando Rust (instantáneo, NO espera el warm del motor).
  const refresh = async () => {
    try {
      const accs = (await window.__TAURI__?.core?.invoke("list_local_accounts")) || [];
      setAccounts(accs);
      accs.forEach((a) => {
        if (a.picture && /\.(png|jpg|jpeg)$/i.test(a.picture)) {
          readImageDataUrl(a.picture).then((s) => s && setAvatars((m) => ({ ...m, [a.email_safe]: s }))).catch(() => {});
        }
      });
    } catch (e) { setAccounts([]); setMsg(String(e.message || e)); }
  };

  // NO llamar set_workspace aquí: persiste folder_roots y con [] borraría la
  // sesión guardada. App carga los roots con ws_load tras el login.
  const enter = (acc) => { onLogin(acc); };
  const loginSaved = async (acc) => {
    setBusy(true); setEntering(acc.email_safe); setMsg("");
    try { const a = await call("oauth_saved", { email: acc.email_safe }); enter({ ...acc, ...a }); }
    catch (e) { setMsg(String(e.message || e)); setEntering(null); setBusy(false); }
  };
  const loginNew = async () => {
    setBusy(true); setEntering("new"); setMsg("Abriendo navegador… autoriza el acceso en Google.");
    try { const a = await call("oauth_login"); enter(a); }
    catch (e) { setMsg(String(e.message || e)); setEntering(null); setBusy(false); }
  };
  const del = async (acc, ev) => {
    ev.stopPropagation();
    const ok = window.confirm(`¿Eliminar la sesión guardada de ${acc.email || acc.name}?`);
    if (!ok) return;
    try {
      await call("delete_account", { email: acc.email_safe });
      try {
        if (window.localStorage?.getItem(LAST_ACCOUNT_KEY) === acc.email_safe) {
          window.localStorage.removeItem(LAST_ACCOUNT_KEY);
        }
      } catch {}
      refresh();
    }
    catch (e) { setMsg(String(e.message || e)); }
  };

  const hasAccounts = accounts && accounts.length > 0;

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#070710] text-white">
      <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-fuchsia-600/15 blur-[130px]" />
      <div className="pointer-events-none absolute -bottom-48 -left-32 h-[520px] w-[520px] rounded-full bg-indigo-700/20 blur-[130px]" />

      <div className="relative z-10 flex h-full min-h-0">
        <HeroColumn />
        <section className="flex flex-1 items-center justify-center px-8 pb-6">
          <div className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-[400px] flex-col rounded-3xl border border-white/10 bg-white/[0.03] p-7 shadow-2xl backdrop-blur-xl">
            <div className="flex min-h-0 flex-1 flex-col animate-[fadeIn_0.25s_ease-out]">
              <h1 className="text-center text-[26px] font-bold leading-tight">¡Bienvenido!</h1>
              <p className="mt-1 text-center text-sm text-neutral-400">
                {hasAccounts ? "Elige tu cuenta para continuar" : "Inicia sesión para continuar"}
              </p>

              {accounts === null ? (
                <p className="mt-8 text-center text-sm text-neutral-500">Cargando…</p>
              ) : (
                <div className="mt-6 flex min-h-0 flex-1 flex-col gap-3">
                  {hasAccounts && (
                    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
                      {accounts.map((a) => {
                        const isEntering = entering === a.email_safe;
                        const dimmed = entering && !isEntering;
                        return (
                          <div key={a.email_safe} onClick={() => !busy && loginSaved(a)}
                            className={`group relative flex items-center gap-3 rounded-xl border p-2.5 transition ${
                              isEntering
                                ? "border-white/10 bg-white/[0.05] cursor-default"
                                : dimmed
                                ? "border-transparent opacity-40 pointer-events-none"
                                : "border-transparent cursor-pointer hover:border-white/10 hover:bg-white/[0.08]"
                            }`}>
                            <div className="h-9 w-9 shrink-0">
                              {avatars[a.email_safe] ? (
                                <img src={avatars[a.email_safe]} alt="" className="h-9 w-9 rounded-full object-cover" />
                              ) : (
                                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-sm font-bold">
                                  {(a.name || a.email || "U").slice(0, 1).toUpperCase()}
                                </div>
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-semibold">{a.name}</div>
                              <div className="truncate text-xs text-neutral-400">
                                {isEntering ? "Entrando…" : a.email}
                              </div>
                            </div>
                            {isEntering ? (
                              <Spinner />
                            ) : (
                              <button onClick={(e) => del(a, e)} title="Eliminar cuenta"
                                className="opacity-0 group-hover:opacity-100 text-neutral-500 hover:text-red-400 px-1">✕</button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {hasAccounts && (
                    <div className="my-1 flex items-center gap-3 text-xs text-neutral-500">
                      <div className="h-px flex-1 bg-white/10" />o continúa con<div className="h-px flex-1 bg-white/10" />
                    </div>
                  )}

                  <GoogleButton onClick={loginNew} disabled={busy} loading={entering === "new"}>
                    {entering === "new" ? "Conectando con Google…" : hasAccounts ? "Agregar otra cuenta" : "Continuar con Google"}
                  </GoogleButton>
                </div>
              )}

              {msg && <p className="mt-4 text-center text-xs text-neutral-400">{msg}</p>}
              <p className="mt-6 text-center text-xs text-neutral-600">© 2026 FaceSync. Todos los derechos reservados.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
