"""Ejecuta la clasificación CR3 natural del Módulo 3 y mide su resultado."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from openpyxl import Workbook

from core.security import SecurityManager
from tools.cr3_evaluator import evaluate_report_assignments, load_manifest
from tools.facesync_tools import FaceSyncCapabilities


DEFAULT_MANIFEST = Path(__file__).with_name("fixtures") / "cr3_ground_truth_current.json"


def _write_natural_excel(path: Path, manifest: dict) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Referencias"
    sheet.append(["Nombre", "Foto"])
    for identity in manifest["identities"]:
        reference_stem = Path(identity["natural_reference"]).stem
        match = re.search(r"(\d+)$", reference_stem)
        numeric = match.group(1) if match else ""
        sheet.append([identity["id"], numeric or reference_stem])
    workbook.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\ianca\Desktop\.cr3"))
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest.resolve())
    source = args.source.resolve()
    run_root = args.run_root.resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"La carpeta de ejecución debe estar vacía: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    destination = run_root / "resultado"
    destination.mkdir()
    table = run_root / "referencias_naturales.xlsx"
    _write_natural_excel(table, manifest)

    os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
    security = SecurityManager(
        str(source.parent), app_data_root=str(run_root / "appdata_limpia")
    )
    motor = FaceSyncCapabilities(
        str(source.parent),
        security_manager=security,
        account_id="module3-cr3-natural",
    )
    report = motor.run_reference_face_matching(
        source_folder=str(source),
        table_path=str(table),
        destination_folder=str(destination),
        name_column="Nombre",
        reference_column="Foto",
        model_name="ArcFace",
        detector_backend="retinaface",
    )
    evaluation = evaluate_report_assignments(manifest, report, "module3_natural")
    artifact = {
        "schema_version": 1,
        "module": 3,
        "source": str(source),
        "success": bool(report.get("success")),
        "error": report.get("error"),
        "report_path": report.get("report_path"),
        "selector": report.get("cr3_reference_selector"),
        "selection_details": report.get("seleccion_referencia_cr3") or [],
        "metrics": evaluation["metrics"],
        "duplicate_assignments": evaluation["duplicate_assignments"],
        "unknown_deliveries": evaluation["unknown_deliveries"],
    }
    output = run_root / "MODULE_3_CR3_NATURAL_EVALUATION.json"
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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
