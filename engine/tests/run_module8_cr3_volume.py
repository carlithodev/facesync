"""Ejecuta 1,000 CR3 sin caché y con caché desde el sidecar empaquetado."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from tests.run_cr2_golden_regression import REPORT_NAMES, _reader, _send, _wait_result


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = PROJECT_ROOT / "engine" / "dist" / "FaceSyncEngine" / "FaceSyncEngine.exe"
DEFAULT_SOURCE = PROJECT_ROOT / ".codex_tmp" / "module8_cr3_20260811" / "volume_source_v1"
DEFAULT_TABLE = PROJECT_ROOT / "outputs" / "module8" / "volume_reference.xlsx"


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _memory_monitor(process: subprocess.Popen[str], stop: threading.Event, result: dict[str, int]) -> None:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    peak = 0
    try:
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        while not stop.wait(0.25):
            if process.poll() is not None:
                break
            if get_memory(int(process._handle), ctypes.byref(counters), counters.cb):
                peak = max(peak, int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize))
    finally:
        result["peak_working_set_bytes"] = peak


def _assignment_snapshot(destination: Path) -> dict[str, Any]:
    paths = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and path.name.lower() not in REPORT_NAMES
    )
    payload = ("\n".join(paths) + "\n").encode("utf-8")
    return {
        "count": len(paths),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "paths": paths,
    }


def _run_once(
    *,
    engine: Path,
    source: Path,
    table: Path,
    local_app_data: Path,
    destination: Path,
    label: str,
    timeout: int,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
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
    stop = threading.Event()
    memory_result: dict[str, int] = {}
    monitor = threading.Thread(
        target=_memory_monitor,
        args=(process, stop, memory_result),
        daemon=True,
    )
    monitor.start()
    started = time.monotonic()
    try:
        account = "module8-cr3-volume@facesync.local"
        roots = [str(source), str(table.parent), str(destination.parent), str(PROJECT_ROOT)]
        _send(process, {"id": f"{label}-workspace", "cmd": "set_workspace", "args": {"roots": roots, "email": account}})
        _wait_result(messages, f"{label}-workspace", 120)
        _send(process, {
            "id": f"{label}-classification",
            "cmd": "classify_start",
            "args": {
                "sources": [str(source)],
                "excel": str(table),
                "destino": str(destination),
                "columna_nombre": "Nombre",
                "columna_referencia": "Código de foto",
                "email": account,
            },
        })
        _wait_result(messages, f"{label}-classification", timeout)
    finally:
        elapsed = time.monotonic() - started
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        stop.set()
        monitor.join(timeout=2)

    report_path = destination / "_reporte_facesync.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    raw = report.get("raw_metrics") or {}
    cache = report.get("cache_metrics") or {}
    required_reports = [destination / name for name in sorted(REPORT_NAMES)]
    return {
        "label": label,
        "elapsed_wall_seconds": round(elapsed, 3),
        "reported_seconds": report.get("tiempo_total"),
        "peak_working_set_bytes": memory_result.get("peak_working_set_bytes", 0),
        "success": report.get("success"),
        "total_found": report.get("fotos_encontradas_total"),
        "total_analyzed": report.get("total_fotos_analizadas"),
        "unique_classified": report.get("total_fotos_unicas_clasificadas"),
        "delivered_files": report.get("archivos_entregados_totales"),
        "unidentified": len(report.get("fotos_no_identificadas") or []),
        "image_errors": len(report.get("errores_imagen") or []),
        "raw_metrics": raw,
        "cache_metrics": cache,
        "cr3_dual_decode": report.get("cr3_dual_decode") or {},
        "reports_present": {path.suffix.lower().lstrip("."): path.is_file() for path in required_reports},
        "assignment_snapshot": _assignment_snapshot(destination),
        "report": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    engine = args.engine.resolve()
    source = args.source.resolve()
    table = args.table.resolve()
    run_root = args.run_root.resolve()
    for required in (engine, source, table):
        if not required.exists():
            raise FileNotFoundError(required)
    source_count = sum(1 for path in source.iterdir() if path.is_file() and path.suffix.lower() == ".cr3")
    if source_count < 1000:
        raise ValueError(f"Se requieren al menos 1,000 CR3; encontrados: {source_count}")
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"La carpeta de ejecución debe estar vacía: {run_root}")
    local_app_data = run_root / "localappdata_persistente"
    local_app_data.mkdir(parents=True, exist_ok=True)

    cold = _run_once(
        engine=engine,
        source=source,
        table=table,
        local_app_data=local_app_data,
        destination=run_root / "cold_output",
        label="cold",
        timeout=args.timeout,
    )
    warm = _run_once(
        engine=engine,
        source=source,
        table=table,
        local_app_data=local_app_data,
        destination=run_root / "warm_output",
        label="warm",
        timeout=args.timeout,
    )

    failures: list[str] = []
    for run in (cold, warm):
        if not run["success"]:
            failures.append(f"{run['label']}: success=false")
        if run["total_found"] != source_count or run["total_analyzed"] != source_count:
            failures.append(f"{run['label']}: no procesó {source_count}/{source_count}")
        if int(run["raw_metrics"].get("cr3_detectadas") or 0) != source_count:
            failures.append(f"{run['label']}: cr3_detectadas distinto de {source_count}")
        if int(run["raw_metrics"].get("raw_errores") or 0) != 0 or run["image_errors"] != 0:
            failures.append(f"{run['label']}: errores RAW o de imagen")
        if not all(run["reports_present"].values()):
            failures.append(f"{run['label']}: faltan reportes")
    if cold["assignment_snapshot"] != warm["assignment_snapshot"]:
        failures.append("Las entregas cambiaron entre la ejecución fría y la ejecución con caché.")
    cold_hits = float(cold["cache_metrics"].get("cache_hit_percent") or 0.0)
    warm_hits = float(warm["cache_metrics"].get("cache_hit_percent") or 0.0)
    if warm_hits <= cold_hits:
        failures.append(f"El caché no aumentó sus aciertos: cold={cold_hits}, warm={warm_hits}")

    artifact = {
        "schema_version": 1,
        "module": 8,
        "test": "cr3_volume_cold_warm",
        "engine": str(engine),
        "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest().upper(),
        "source": str(source),
        "source_cr3_count": source_count,
        "source_note": "Lote técnico con enlaces duros: 999 controles CR3 sin persona y una referencia humana. Mide volumen/estabilidad, no diversidad facial.",
        "cold": cold,
        "warm": warm,
        "cache_speedup_ratio": round(cold["elapsed_wall_seconds"] / warm["elapsed_wall_seconds"], 4) if warm["elapsed_wall_seconds"] else None,
        "assignments_identical": cold["assignment_snapshot"] == warm["assignment_snapshot"],
        "failures": failures,
        "passed": not failures,
    }
    output = run_root / "MODULE_8_CR3_VOLUME.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "passed": not failures,
        "source_cr3_count": source_count,
        "cold_seconds": cold["elapsed_wall_seconds"],
        "warm_seconds": warm["elapsed_wall_seconds"],
        "cold_cache_percent": cold_hits,
        "warm_cache_percent": warm_hits,
        "cold_peak_bytes": cold["peak_working_set_bytes"],
        "warm_peak_bytes": warm["peak_working_set_bytes"],
        "assignments_identical": artifact["assignments_identical"],
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
