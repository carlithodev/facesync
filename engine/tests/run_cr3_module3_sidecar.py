"""Valida el Módulo 3 CR3 usando el sidecar PyInstaller empaquetado."""

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

from tests.run_cr2_golden_regression import _reader, _send
from tests.run_cr3_module3_classification import _write_natural_excel
from tools.cr3_evaluator import evaluate_report_assignments, load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = PROJECT_ROOT / "engine" / "dist" / "FaceSyncEngine" / "FaceSyncEngine.exe"
DEFAULT_MANIFEST = Path(__file__).with_name("fixtures") / "cr3_ground_truth_current.json"


def _wait(messages: queue.Queue[str | None], request_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_stage = ""
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            raise RuntimeError("El sidecar terminó antes de entregar el resultado.")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("id") != request_id:
            continue
        if event.get("type") == "progress":
            stage = str((event.get("data") or {}).get("stage") or "")
            if stage and stage != last_stage:
                print(f"[CR3 sidecar] {stage}", flush=True)
                last_stage = stage
            continue
        if event.get("type") == "error" or event.get("ok") is False:
            raise RuntimeError(f"El sidecar devolvió error: {event}")
        if event.get("type") == "result":
            return event
    raise TimeoutError(f"El sidecar no terminó en {timeout} segundos.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\ianca\Desktop\.cr3"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    engine = args.engine.resolve()
    manifest = load_manifest(args.manifest.resolve())
    source = args.source.resolve()
    run_root = args.run_root.resolve()
    if not engine.is_file() or not source.is_dir():
        raise FileNotFoundError("Falta el sidecar o el conjunto CR3.")
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"La carpeta de ejecución debe estar vacía: {run_root}")
    destination = run_root / "resultado"
    local_app_data = run_root / "localappdata_limpia"
    destination.mkdir(parents=True, exist_ok=True)
    local_app_data.mkdir()
    table = run_root / "referencias_naturales.xlsx"
    _write_natural_excel(table, manifest)

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
        account = "module3-cr3-sidecar@facesync.local"
        _send(process, {
            "id": "module3-workspace",
            "cmd": "set_workspace",
            "args": {
                "roots": [str(source), str(run_root), str(PROJECT_ROOT)],
                "email": account,
            },
        })
        _wait(messages, "module3-workspace", 120)
        _send(process, {
            "id": "module3-classification",
            "cmd": "classify_start",
            "args": {
                "sources": [str(source)],
                "excel": str(table),
                "destino": str(destination),
                "columna_nombre": "Nombre",
                "columna_referencia": "Foto",
                "email": account,
            },
        })
        _wait(messages, "module3-classification", args.timeout)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(local_app_data, ignore_errors=True)

    report_path = destination / "_reporte_facesync.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    evaluation = evaluate_report_assignments(manifest, report, "module3_sidecar")
    artifact = {
        "schema_version": 1,
        "module": 3,
        "engine": str(engine),
        "engine_sha256": __import__("hashlib").sha256(engine.read_bytes()).hexdigest().upper(),
        "report_path": str(report_path),
        "selector": report.get("cr3_reference_selector"),
        "selection_details": report.get("seleccion_referencia_cr3") or [],
        "metrics": evaluation["metrics"],
        "duplicate_assignments": evaluation["duplicate_assignments"],
        "unknown_deliveries": evaluation["unknown_deliveries"],
    }
    output = run_root / "MODULE_3_CR3_SIDECAR_EVALUATION.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    overall = artifact["metrics"]["overall"]
    print(json.dumps({
        "output": str(output),
        "precision": overall["precision"],
        "recall": overall["recall"],
        "correct": overall["correct_photos"],
        "predicted": overall["predicted_photos"],
        "targets": overall["target_photos"],
        "promoted_references": (artifact["selector"] or {}).get("promoted_references"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

