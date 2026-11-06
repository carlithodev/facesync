"""Ejecuta el diagnóstico CR3 del Módulo 1 desde el sidecar empaquetado."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = PROJECT_ROOT / "engine" / "dist" / "FaceSyncEngine" / "FaceSyncEngine.exe"
DEFAULT_MANIFEST = Path(__file__).with_name("fixtures") / "cr3_ground_truth_current.json"


def _reader(stream: Any, messages: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            messages.put(line.rstrip("\r\n"))
    finally:
        messages.put(None)


def _send(process: subprocess.Popen[str], request: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _wait_result(
    messages: queue.Queue[str | None], request_id: str, timeout: int
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_percent = -10
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            raise RuntimeError("El sidecar terminó antes de devolver el resultado.")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("id") != request_id:
            continue
        if event.get("type") == "progress":
            data = event.get("data") or {}
            percent = int(data.get("percent") or 0)
            if percent >= last_percent + 10:
                print(f"[CR3] {percent}% {data.get('message') or ''}", flush=True)
                last_percent = percent
            continue
        if event.get("type") == "error" or event.get("ok") is False:
            raise RuntimeError(f"El sidecar devolvió error: {event}")
        if event.get("type") == "result":
            data = event.get("data") or {}
            if data.get("ok") is False:
                raise RuntimeError(data.get("traceback") or str(data))
            return data
    raise TimeoutError(f"El diagnóstico no terminó en {timeout} segundos.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\ianca\Desktop\.cr3"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    engine = args.engine.resolve()
    manifest = args.manifest.resolve()
    source = args.source.resolve()
    run_root = args.run_root.resolve()
    if not engine.is_file() or not manifest.is_file() or not source.is_dir():
        raise FileNotFoundError("Falta el sidecar, manifiesto o conjunto CR3.")
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"La carpeta de ejecución debe estar vacía: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    output = run_root / "cr3_measurements.json"
    local_app_data = run_root / "localappdata_clean"
    local_app_data.mkdir()

    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(local_app_data)
    environment["TF_USE_LEGACY_KERAS"] = "1"
    process = subprocess.Popen(
        [str(engine)],
        cwd=str(engine.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    assert process.stdout is not None
    messages: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_reader, args=(process.stdout, messages), daemon=True).start()
    try:
        account = "module1-cr3-evaluator@facesync.local"
        _send(process, {
            "id": "module1-workspace",
            "cmd": "set_workspace",
            "args": {"roots": [str(source), str(PROJECT_ROOT)], "email": account},
        })
        _wait_result(messages, "module1-workspace", 120)
        _send(process, {
            "id": "module1-measurements",
            "cmd": "diag_cr3_measurements",
            "args": {
                "manifest": str(manifest),
                "source_folder": str(source),
                "output": str(output),
                "email": account,
            },
        })
        result = _wait_result(messages, "module1-measurements", args.timeout)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(local_app_data, ignore_errors=True)
    if not output.is_file():
        raise RuntimeError("El diagnóstico no generó el JSON esperado.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
