"""Valida en una ejecución conjunta JPG, CR2 y CR3 desde el sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from tests.run_cr2_golden_regression import REPORT_NAMES, _reader, _send, _wait_result
from tools.cr3_evaluator import evaluate_report_assignments, load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = PROJECT_ROOT / "engine" / "dist" / "FaceSyncEngine" / "FaceSyncEngine.exe"
DEFAULT_BASELINE = PROJECT_ROOT / "docs" / "baselines" / "MODULE_0_CR2_BASELINE.json"
DEFAULT_MANIFEST = Path(__file__).with_name("fixtures") / "cr3_ground_truth_current.json"
DEFAULT_TABLE = PROJECT_ROOT / "outputs" / "module8" / "mixed_references.xlsx"
CR3_FOLDERS = {"ATLETA", "BAILARINA"}


def _filtered_snapshot(destination: Path) -> dict[str, Any]:
    paths = sorted(
        (
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
            and path.name.lower() not in REPORT_NAMES
            and path.relative_to(destination).parts[0] not in CR3_FOLDERS
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--cr3-source", type=Path, default=Path(r"C:\Users\ianca\Desktop\.cr3"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()

    engine = args.engine.resolve()
    baseline = json.loads(args.baseline.resolve().read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest.resolve())
    table = args.table.resolve()
    cr2_source = Path(baseline["inputs"]["source"]).resolve()
    cr3_source = args.cr3_source.resolve()
    run_root = args.run_root.resolve()
    for required in (engine, table, cr2_source, cr3_source):
        if not required.exists():
            raise FileNotFoundError(required)
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
        account = "module8-mixed-sidecar@facesync.local"
        roots = [str(cr2_source), str(cr3_source), str(table.parent), str(run_root), str(PROJECT_ROOT)]
        _send(process, {"id": "m8-workspace", "cmd": "set_workspace", "args": {"roots": roots, "email": account}})
        _wait_result(messages, "m8-workspace", 120)
        _send(process, {
            "id": "m8-classification",
            "cmd": "classify_start",
            "args": {
                "sources": [str(cr2_source), str(cr3_source)],
                "excel": str(table),
                "destino": str(destination),
                "columna_nombre": "Nombre",
                "columna_referencia": "Código de foto",
                "email": account,
            },
        })
        _wait_result(messages, "m8-classification", args.timeout)
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
    golden = baseline["golden_profile"]
    cr2_actual = _filtered_snapshot(destination)
    cr2_expected = {
        key: golden[key]
        for key in ("assignment_manifest_sha256", "assignment_count", "by_person", "by_extension")
    }
    cr3_evaluation = evaluate_report_assignments(manifest, report, "module8_mixed")
    cr3_metrics = cr3_evaluation["metrics"]["overall"]
    cr3_deliveries = sorted(
        path.relative_to(destination).as_posix()
        for folder in CR3_FOLDERS
        for path in (destination / folder).glob("*.cr3")
    )
    required_reports = [destination / name for name in sorted(REPORT_NAMES)]
    failures: list[str] = []
    if cr2_actual != cr2_expected:
        failures.append("La firma JPG/CR2 cambió dentro del lote mixto.")
    if not (
        cr3_metrics.get("correct_photos") == 23
        and cr3_metrics.get("predicted_photos") == 23
        and cr3_metrics.get("target_photos") == 23
    ):
        failures.append(f"Resultado CR3 distinto de 23/23: {cr3_metrics}")
    if len(cr3_deliveries) != 23:
        failures.append(f"Se entregaron {len(cr3_deliveries)} originales CR3, se esperaban 23.")
    if any(not path.is_file() for path in required_reports):
        failures.append("Falta al menos uno de los reportes JSON/TXT/XLSX.")
    if report.get("errores_imagen") or (report.get("raw_metrics") or {}).get("raw_errores"):
        failures.append("La ejecución mixta reportó errores de imagen o RAW.")

    artifact = {
        "schema_version": 1,
        "module": 8,
        "test": "mixed_jpg_cr2_cr3_sidecar",
        "engine": str(engine),
        "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest().upper(),
        "sources": [str(cr2_source), str(cr3_source)],
        "report": str(report_path),
        "report_files": {path.suffix.lower().lstrip("."): path.is_file() for path in required_reports},
        "report_summary": {
            "success": report.get("success"),
            "total_personas": report.get("total_personas"),
            "total_fotos_analizadas": report.get("total_fotos_analizadas"),
            "archivos_entregados_totales": report.get("archivos_entregados_totales"),
            "raw_metrics": report.get("raw_metrics"),
            "cr3_dual_decode": report.get("cr3_dual_decode"),
        },
        "cr2_expected": cr2_expected,
        "cr2_actual": cr2_actual,
        "cr2_exact_signature_preserved": cr2_actual == cr2_expected,
        "cr3_metrics": cr3_metrics,
        "cr3_originals_delivered": len(cr3_deliveries),
        "cr3_duplicate_assignments": cr3_evaluation["duplicate_assignments"],
        "cr3_unknown_deliveries": cr3_evaluation["unknown_deliveries"],
        "failures": failures,
        "passed": not failures,
    }
    output = run_root / "MODULE_8_MIXED_SIDECAR.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "passed": not failures,
        "cr2_assignments": cr2_actual["assignment_count"],
        "cr2_exact": cr2_actual == cr2_expected,
        "cr3_correct": cr3_metrics.get("correct_photos"),
        "cr3_targets": cr3_metrics.get("target_photos"),
        "cr3_originals": len(cr3_deliveries),
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
