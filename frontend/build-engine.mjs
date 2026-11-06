import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = dirname(fileURLToPath(import.meta.url));
const engineDir = resolve(frontendDir, "..", "engine");
const venvPython = join(engineDir, "env_ia", "Scripts", "python.exe");
const output = join(engineDir, "dist", "FaceSyncEngine");
const staged = join(frontendDir, "src-tauri", "resources", "engine");

const candidates = existsSync(venvPython) ? [venvPython, "python"] : ["python"];
const python = candidates.find((candidate) => {
  const probe = spawnSync(candidate, ["-m", "PyInstaller", "--version"], { cwd: engineDir, encoding: "utf8" });
  return probe.status === 0;
});
if (!python) {
  throw new Error("PyInstaller no está disponible. Instala engine/requirements.txt en Python 3.11.");
}

const build = spawnSync(
  python,
  ["-m", "PyInstaller", "--noconfirm", "FaceSyncEngine.spec"],
  { cwd: engineDir, stdio: "inherit" },
);
if (build.status !== 0 || !existsSync(join(output, "FaceSyncEngine.exe"))) {
  throw new Error("No se pudo generar el sidecar FaceSyncEngine.");
}

rmSync(staged, { recursive: true, force: true });
mkdirSync(staged, { recursive: true });
cpSync(output, staged, { recursive: true });
