import { useEffect, useState } from "react";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { onReady, isEngineReady, call } from "./lib/sidecar";
import { readImageDataUrl } from "./lib/native";
import Login from "./sections/Login";
import TitleBar from "./components/TitleBar";
import SectionsBar from "./components/SectionsBar";
import SettingsMenu from "./components/SettingsMenu";
import Workspace from "./sectio''ns/Workspace";
import Reportes from "./sections/Reportes";
import Exportaciones from "./sections/Exportaciones";

const LAST_ACCOUNT_KEY = "facesync:last-account";

function appWindow() {
  return window.__TAURI__?.window?.getCurrentWindow?.();
}

function readLastAccount() {
  try { return window.localStorage?.getItem(LAST_ACCOUNT_KEY) || ""; }
  catch { return ""; }
}

function rememberLastAccount(acc) {
  const email = acc?.email_safe || acc?.email || "";
  if (!email) return;
  try { window.localStorage?.setItem(LAST_ACCOUNT_KEY, email); }
  catch {}
}

function forgetLastAccount() {
  try { window.localStorage?.removeItem(LAST_ACCOUNT_KEY); }
  catch {}
}

function accountSeedFromStorage() {
  const email = readLastAccount();
  if (!email) return null;
  const name = email.split("@")[0]?.replace(/[._-]+/g, " ") || email;
  return { email_safe: email, email, name };
}

function sameAccount(user, email) {
  return Boolean(user && email && (user.email_safe === email || user.email === email));
}

export default function App() {
  const [user, setUser] = useState(() => accountSeedFromStorage());
  const [section, setSection] = useState("workspace");
  const [ready, setReady] = useState(isEngineReady());
  const [roots, setRootsState] = useState([]);
  const [avatar, setAvatar] = useState(null);
  const userEmail = user?.email_safe || user?.email || "";

  useEffect(() => onReady(() => setReady(true)), []);

  useEffect(() => {
    if (!userEmail) return;
    let cancelled = false;
    const hydrateLocalAccount = async () => {
      try {
        const accounts = (await window.__TAURI__?.core?.invoke("list_local_accounts")) || [];
        const acc = accounts.find((a) => a.email_safe === userEmail || a.email === userEmail);
        if (cancelled) return;
        if (acc) {
          setUser((current) => (sameAccount(current, userEmail) ? { ...current, ...acc } : current));
        } else if (readLastAccount() === userEmail) {
          call("chat_logout", { email: userEmail }).catch(() => {});
          forgetLastAccount();
          setUser(null);
          setRootsState([]);
        }
      } catch {}
    };
    hydrateLocalAccount();
    return () => { cancelled = true; };
  }, [userEmail]);

  useEffect(() => {
    if (!ready || !userEmail || readLastAccount() !== userEmail) return;

    let cancelled = false;
    call("oauth_saved", { email: userEmail })
      .then((acc) => {
        if (cancelled) return;
        rememberLastAccount(acc);
        setUser((current) => (sameAccount(current, userEmail) ? { ...current, ...acc } : current));
      })
      .catch(() => {
        if (cancelled) return;
        call("chat_logout", { email: userEmail }).catch(() => {});
        forgetLastAccount();
        setUser(null);
        setRootsState([]);
      })
    return () => { cancelled = true; };
  }, [ready, userEmail]);

  useEffect(() => {
    const w = appWindow();
    if (!w) return;
    if (user) {
      // Tamaño mínimo: por debajo de esto el layout de 3 columnas se aprieta.
      // Se bloquea el resize por debajo de esta medida.
      Promise.resolve(w.setMinSize?.(new LogicalSize(1000, 640))).catch(() => {});
      w.setResizable?.(true);
      w.maximize?.();
    } else {
      Promise.resolve(w.setMinSize?.(new LogicalSize(1000, 640))).catch(() => {});
      w.unmaximize?.();
      w.setResizable?.(false);
    }
  }, [user]);

  useEffect(() => {
    if (user?.picture && /\.(png|jpg|jpeg)$/i.test(user.picture)) {
      readImageDataUrl(user.picture).then((s) => s && setAvatar(s)).catch(() => {});
    } else setAvatar(null);
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let on = true;
    let unsubscribe = () => {};
    const load = () => call("ws_load", { email: user.email_safe || user.email }).then((d) => { if (on) setRootsState(d.roots || []); }).catch(() => {});
    if (ready) load(); else unsubscribe = onReady(load);
    return () => { on = false; unsubscribe(); };
  }, [user, ready]);

  const setRoots = (next) => {
    setRootsState(next);
    const email = user?.email_safe || user?.email;
    if (!email) { console.warn("set_workspace omitido: sin email de cuenta"); return; }
    call("set_workspace", { email, roots: next }).catch((e) => console.error("set_workspace fallo:", e));
  };

  const handleLogin = (acc) => {
    rememberLastAccount(acc);
    setUser(acc);
  };

  const handleLogout = () => {
    if (userEmail) call("chat_logout", { email: userEmail }).catch(() => {});
    forgetLastAccount();
    setUser(null);
    setSection("workspace");
    setRootsState([]);
  };

  const props = { user, roots, setRoots };
  // Cross-fade entre secciones: las tres quedan montadas (preserva estado y
  // listeners); solo cambia opacidad. La inactiva no captura clics. Devolvemos
  // solo la clase (no un componente) para no remontar las vistas en cada render.
  const paneCls = (k) =>
    `absolute inset-0 transition-opacity duration-300 ease-out ${
      section === k ? "opacity-100" : "pointer-events-none opacity-0"
    }`;

  return (
    // Raíz fija al viewport. onScroll: si algún scrollIntoView intentara mover
    // este contenedor con overflow-hidden, lo reseteamos (defensa extra; la causa
    // real -el scrollIntoView del chat- ya se quitó).
    <div
      className="fixed inset-0 overflow-hidden bg-[#070710] text-white"
      onScroll={(e) => { e.currentTarget.scrollTop = 0; e.currentTarget.scrollLeft = 0; }}
    >
      <TitleBar />

      {!user ? (
        <div className="absolute inset-0">
          <Login onLogin={handleLogin} />
        </div>
      ) : (
        <div className="absolute inset-0 bg-[#070710] text-slate-100">
          <div className="pointer-events-none absolute -right-40 -top-40 h-[420px] w-[420px] rounded-full bg-fuchsia-600/10 blur-[130px]" />
          <div className="pointer-events-none absolute -bottom-48 left-1/4 h-[420px] w-[420px] rounded-full bg-indigo-700/10 blur-[130px]" />

          <SectionsBar
            section={section} setSection={setSection} user={user} avatar={avatar}
            onLogout={handleLogout}
          />
          <SettingsMenu ready={ready} roots={roots} user={user} />

          {/* Área de contenido: pegada al viewport, deja hueco izq para el rail */}
          <div className="absolute inset-0 z-0 pl-24">
            <div className="relative h-full">
              <div className={paneCls("workspace")}><Workspace {...props} /></div>
              <div className={paneCls("reportes")}><Reportes {...props} active={section === "reportes"} /></div>
              <div className={paneCls("exportaciones")}><Exportaciones {...props} active={section === "exportaciones"} /></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
