import { open } from "@tauri-apps/plugin-dialog";
import { call } from "./sidecar";

// Helpers nativos: selectores de archivo/carpeta (plugin dialog), lectura de
// imagen a data-URL (Rust read_file_b64) y miniatura/preview (sidecar
// read_thumb, que además soporta CR2/RAW vía su JPEG embebido).

const TAURI = typeof window !== "undefined" && window.__TAURI__;

export async function pickFolder() {
  const r = await open({ directory: true, multiple: false });
  return typeof r === "string" ? r : null;
}

export async function pickFile(filters) {
  const r = await open({ multiple: false, filters });
  return typeof r === "string" ? r : null;
}

export async function createExcelTemplate(name, directory, roots) {
  if (!TAURI) throw new Error("sin Tauri");
  return window.__TAURI__.core.invoke("create_excel_template", {
    name,
    directory,
    roots: roots || [],
  });
}

export async function openExcelFile(path, roots) {
  if (!TAURI) throw new Error("sin Tauri");
  return window.__TAURI__.core.invoke("open_excel_file", {
    path,
    roots: roots || [],
  });
}

export async function openDriveFolder(folderId = null) {
  if (!TAURI) throw new Error("sin Tauri");
  return window.__TAURI__.core.invoke("open_drive_folder", {
    folderId: folderId || null,
  });
}

const IMG_MIME = { jpg: "jpeg", jpeg: "jpeg", png: "png", gif: "gif", bmp: "bmp", webp: "webp" };
// RAW que el webview NO decodifica, pero sí se previsualizan vía read_thumb.
const RAW_EXTS = new Set(["cr2", "cr3", "nef", "arw", "dng", "raf", "rw2", "orf", "srw"]);

const extOf = (name) => (name.split(".").pop() || "").toLowerCase();

export function isImage(name) {
  const ext = extOf(name);
  return !!IMG_MIME[ext] || RAW_EXTS.has(ext);
}

export function isRaw(name) {
  return RAW_EXTS.has(extOf(name));
}

// Carga directa (web): solo formatos que el navegador decodifica. RAW -> null.
export async function readImageDataUrl(path) {
  if (!TAURI) return null;
  const mime = IMG_MIME[extOf(path)];
  if (!mime) return null;
  const b64 = await window.__TAURI__.core.invoke("read_file_b64", { path });
  return `data:image/${mime};base64,${b64}`;
}

// Miniatura/preview (sidecar). Funciona para JPG/PNG y CR2/RAW por igual:
// devuelve un JPEG ligero. size = lado mayor del thumbnail.
// Propaga el error de 'call' a proposito: makeThumb (thumbs.js) lo necesita
// para distinguir "sidecar ocupado" (reintentar) de "sin preview" (null).
export async function readThumb(path, size = 256) {
  if (!TAURI) return null;
  const r = await call("read_thumb", { path, size });
  const b64 = typeof r === "string" ? r : r?.data;
  return b64 ? `data:image/jpeg;base64,${b64}` : null;
}
