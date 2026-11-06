// beforeDevCommand de Tauri: levanta Vite en el puerto 1420 (devUrl).
// FaceSyncV2 no usa backend HTTP: el motor IA va por sidecar (stdin/stdout)
// arrancado desde Rust. Aquí solo arrancamos el front.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const vite = spawn("npx", ["vite"], { cwd: here, stdio: "inherit", shell: true });
vite.on("exit", (code) => process.exit(code ?? 0));
