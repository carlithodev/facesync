"""Ejecuta o verifica la regresión dorada JPG/CR2 de FaceSync.

Este archivo pertenece únicamente a pruebas. No se importa desde producción y
no modifica el motor de reconocimiento.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = PROJECT_ROOT / "docs" / "baselines" / "MODULE_0_CR2_BASELINE.json"
REPORT_NAMES = {
    "_reporte_facesync.json",
    "_reporte_facesync.txt",
    "_reporte_facesync.xlsx",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assignment_snapshot(destination: Path) -> dict[str, Any]:
    paths = sorted(
        (
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file() and path.name.lower() not in REPORT_NAMES
        ),
        key=lambda value: (value.casefold(), value),
    )
    payload = ("\n".join(paths) + "\n").encode("utf-8")
    by_person: Counter[str] = Counter()
    by_extension: Counter[str] = Counter()
    for relative in paths:
        by_person[relative.split("/", 1)[0]] += 1
        by_extension[Path(relative).suffix.upper()] += 1
    return {
        "assignment_manifest_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "assignment_count": len(paths),
        "by_person": dict(sorted(by_person.items())),
        "by_extension": dict(sorted(by_extension.items())),
    }


def report_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    cr2_metrics = report.get("cr2_metrics") or {}
    cr3_dual = report.get("cr3_dual_decode") or {}
    performance = report.get("performance_stats") or {}
    cache = report.get("cache_metrics") or {}
    return {
        "success": report.get("success"),
        "total_personas": report.get("total_personas"),
        "total_referencias": report.get("total_referencias"),
        "referencias_encontradas": report.get("referencias_encontradas"),
        "referencias_faltantes_count": len(report.get("referencias_faltantes") or []),
        "referencias_ambiguas_count": len(report.get("referencias_ambiguas") or []),
        "total_fotos_analizadas": report.get("total_fotos_analizadas"),
        "fotos_analizadas_reales": report.get("fotos_analizadas_reales"),
        "total_fotos_copiadas": report.get("total_fotos_copiadas"),
        "archivos_entregados_totales": report.get("archivos_entregados_totales"),
        "total_fotos_unicas_clasificadas": report.get("total_fotos_unicas_clasificadas"),
        "fotos_ignoradas_no_asignadas_count": len(report.get("fotos_ignoradas_no_asignadas") or []),
        "conflictos_identidad_count": len(report.get("conflictos_identidad") or []),
        "errores_imagen_count": len(report.get("errores_imagen") or []),
        "raw_omitidos_por_jpg_gemelo": report.get("raw_omitidos_por_jpg_gemelo"),
        "cr2_omitidos_por_jpg_gemelo": report.get("cr2_omitidos_por_jpg_gemelo"),
        "raw_gemelos_copiados": report.get("raw_gemelos_copiados"),
        "cr2_gemelos_copiados": report.get("cr2_gemelos_copiados"),
        "cache_hit_percent": cache.get("cache_hit_percent"),
        "cr2_detectadas": cr2_metrics.get("cr2_detectadas"),
        "cr2_errores": cr2_metrics.get("cr2_errores"),
        "cr3_detectadas": cr2_metrics.get("cr3_detectadas"),
        "cr3_fullraw_enabled": cr3_dual.get("enabled"),
        "cr3_fullraw_processed": cr3_dual.get("fullraw_processed"),
        "performance_backend": performance.get("backend"),
    }


def compare_mapping(label: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            failures.append(f"{label}.{key}: esperado={expected_value!r}, actual={actual_value!r}")
    return failures


def verify(baseline_path: Path, report_path: Path, destination: Path) -> list[str]:
    baseline = load_json(baseline_path)["golden_profile"]
    report = load_json(report_path)
    failures = compare_mapping(
        "reporte",
        baseline["report_expectations"],
        report_snapshot(report),
    )
    expected_assignments = {
        key: baseline[key]
        for key in ("assignment_manifest_sha256", "assignment_count", "by_person", "by_extension")
    }
    failures.extend(
        compare_mapping("asignaciones", expected_assignments, assignment_snapshot(destination))
    )
    return failures


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
    messages: queue.Queue[str | None],
    request_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_stage = ""
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            raise RuntimeError("El ejecutable terminó antes de entregar el resultado.")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("id") != request_id:
            continue
        if event.get("type") == "progress":
            stage = str((event.get("data") or {}).get("stage") or "")
            if stage and stage != last_stage:
                print(f"[FaceSync] {stage}", flush=True)
                last_stage = stage
            continue
        if event.get("type") == "error" or event.get("ok") is False:
            raise RuntimeError(f"FaceSync devolvió error: {event}")
        if event.get("type") == "result":
            return event
    raise TimeoutError(f"FaceSync no terminó en {timeout_seconds} segundos.")


def run_golden(
    baseline_path: Path,
    run_root: Path,
    timeout_seconds: int,
    engine_override: Path | None = None,
) -> tuple[Path, Path]:
    baseline = load_json(baseline_path)
    inputs = baseline["inputs"]
    source = Path(inputs["source"])
    excel = Path(inputs["excel"])
    engine = engine_override or (PROJECT_ROOT / baseline["initial_version"]["packaged_engine"]["path"])
    if not source.is_dir() or not excel.is_file() or not engine.is_file():
        raise FileNotFoundError("Falta el lote, Excel o ejecutable registrado en la línea base.")
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"La carpeta de ejecución debe estar vacía: {run_root}")
    destination = run_root / "output"
    local_app_data = run_root / "localappdata_clean"
    destination.mkdir(parents=True, exist_ok=True)
    local_app_data.mkdir(parents=True, exist_ok=True)

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
        account = "module0-cr2-regression@facesync.local"
        roots = [str(source), str(excel.parent), str(PROJECT_ROOT)]
        _send(process, {"id": "golden-workspace", "cmd": "set_workspace", "args": {"roots": roots, "email": account}})
        _wait_result(messages, "golden-workspace", 120)
        _send(
            process,
            {
                "id": "golden-classification",
                "cmd": "classify_start",
                "args": {
                    "sources": [str(source)],
                    "excel": str(excel),
                    "destino": str(destination),
                    "columna_nombre": inputs["name_column"],
                    "columna_referencia": inputs["reference_column"],
                    "email": account,
                },
            },
        )
        _wait_result(messages, "golden-classification", timeout_seconds)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(local_app_data, ignore_errors=True)
    return destination / "_reporte_facesync.json", destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--report", type=Path, help="Reporte existente para verificación rápida.")
    parser.add_argument("--destination", type=Path, help="Destino existente asociado al reporte.")
    parser.add_argument("--run-root", type=Path, help="Ejecuta desde cero dentro de esta carpeta vacía.")
    parser.add_argument("--engine", type=Path, help="Ejecutable empaquetado que se desea verificar.")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    if args.run_root:
        report, destination = run_golden(
            args.baseline.resolve(),
            args.run_root.resolve(),
            args.timeout,
            args.engine.resolve() if args.engine else None,
        )
    elif args.report and args.destination:
        report, destination = args.report.resolve(), args.destination.resolve()
    else:
        parser.error("Use --run-root, o bien --report junto con --destination.")

    failures = verify(args.baseline.resolve(), report, destination)
    if failures:
        print("REGRESIÓN CR2: FALLÓ")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("REGRESIÓN CR2: APROBADA")
    print(f"Reporte: {report}")
    print(f"Destino: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
