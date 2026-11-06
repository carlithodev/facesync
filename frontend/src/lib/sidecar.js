// Cliente del sidecar Python. Backbone de toda la app:
// - Escucha los eventos que emite Rust (sidecar://msg = protocolo JSON).
// - Despacha cada respuesta a la promesa pendiente por su id.
// - Soporta streaming: las respuestas type:"progress" llaman onProgress;
//   type:"result" resuelve; type:"error" rechaza.
//
// API:
//   call(cmd, args, onProgress) -> Promise<data>
//   cancel(targetId) -> Promise
//   onReady(cb), isEngineReady(), onLog(cb)

const TAURI = typeof window !== "undefined" && window.__TAURI__;

let nextId = 1;
const pending = new Map(); // id -> { resolve, reject, onProgress }
const logListeners = [];
const readyListeners = [];
let engineReady = false;

const TIMEOUT_BY_COMMAND = {
  classify_start: 6 * 60 * 60 * 1000,
  drive_export_start: 12 * 60 * 60 * 1000,
  oauth_login: 15 * 60 * 1000,
  chat_send: 6 * 60 * 60 * 1000,
  storage_usage: 15 * 60 * 1000,
};
const DEFAULT_TIMEOUT = 2 * 60 * 1000;

export function isEngineReady() {
  return engineReady;
}
export function onReady(cb) {
  if (engineReady) {
    cb();
    return () => {};
  }
  readyListeners.push(cb);
  return () => {
    const i = readyListeners.indexOf(cb);
    if (i >= 0) readyListeners.splice(i, 1);
  };
}
export function onLog(cb) {
  logListeners.push(cb);
  return () => {
    const i = logListeners.indexOf(cb);
    if (i >= 0) logListeners.splice(i, 1);
  };
}

function handleMsg(raw) {
  let m;
  try {
    m = JSON.parse(raw);
  } catch {
    return;
  }
  if (m.type === "ready") {
    engineReady = true;
    readyListeners.splice(0).forEach((c) => c());
    return;
  }
  if (m.type === "starting") return;
  const p = pending.get(m.id);
  if (!p) return;
  if (m.type === "progress") {
    p.onProgress && p.onProgress(m.data);
  } else if (m.type === "result") {
    pending.delete(m.id);
    clearTimeout(p.timer);
    p.resolve(m.data);
  } else if (m.type === "error") {
    pending.delete(m.id);
    clearTimeout(p.timer);
    p.reject(new Error(m.error));
  }
}

function failAll(reason) {
  engineReady = false;
  for (const [id, p] of pending) {
    pending.delete(id);
    clearTimeout(p.timer);
    p.reject(new Error(reason));
  }
}

export function call(cmd, args, onProgress, onStart) {
  const id = String(nextId++);
  return new Promise((resolve, reject) => {
    if (!TAURI) {
      reject(new Error("sin Tauri (corre con `npm run tauri dev`)"));
      return;
    }
    const timeout = TIMEOUT_BY_COMMAND[cmd] || DEFAULT_TIMEOUT;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`el motor no respondio a '${cmd}' dentro del tiempo esperado`));
    }, timeout);
    pending.set(id, { resolve, reject, onProgress, timer });
    // Expone el id de la petición para poder cancelar el job (cancel(id)).
    if (onStart) { try { onStart(id); } catch {} }
    const line = JSON.stringify({ id, cmd, args: args || {} });
    window.__TAURI__.core.invoke("sidecar_send", { line }).catch((e) => {
      const current = pending.get(id);
      pending.delete(id);
      if (current) clearTimeout(current.timer);
      reject(e);
    });
  });
}

export function cancel(targetId) {
  return call("cancel", { target_id: targetId });
}

if (TAURI) {
  const { listen } = window.__TAURI__.event;
  listen("sidecar://msg", (e) => handleMsg(e.payload)).catch(() => {});
  listen("sidecar://log", (e) => logListeners.forEach((c) => c(e.payload))).catch(() => {});
  listen("sidecar://error", (e) => {
    const message = "ERROR " + e.payload;
    logListeners.forEach((c) => c(message));
    failAll(message);
  }).catch(() => {});
  listen("sidecar://closed", () => failAll("el motor se cerro inesperadamente")).catch(() => {});
}
