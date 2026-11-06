"""Genera el reporte reproducible del Módulo 1 a partir de verdad y mediciones."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.cr3_evaluator import evaluate_report_assignments, load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("fixtures") / "cr3_ground_truth_current.json"


def _percent(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.1f}%"


def _load_report(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(manifest: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    runs = []
    for definition in manifest.get("baseline_runs") or []:
        report = _load_report(definition["report"])
        evaluation = evaluate_report_assignments(manifest, report, definition["name"])
        evaluation["source_report"] = definition["report"]
        evaluation["note"] = definition.get("note")
        runs.append(evaluation)
    return {
        "schema_version": 1,
        "module": 1,
        "purpose": "Medición facial y verdad de referencia CR3",
        "manifest_summary": manifest["annotation_scope"],
        "identities": manifest["identities"],
        "classification_runs": runs,
        "representation_diagnostics": diagnostics,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Módulo 1 — Medición facial y verdad de referencia CR3",
        "",
        "## Conjunto etiquetado",
        "",
        f"- Fotografías CR3: `{report['manifest_summary']['photos']}`.",
        f"- Fotografías humanas objetivo: `{report['manifest_summary']['human_target_photos']}`.",
        f"- Fotografías sin identidad objetivo: `{report['manifest_summary']['no_target_photos']}`.",
        f"- Fotografías grupales: `{report['manifest_summary']['group_photos']}`.",
        f"- Fotografías con acompañantes humanos: `{report['manifest_summary']['photos_with_human_companions']}`.",
        "",
        "## Precisión y cobertura de las ejecuciones existentes",
        "",
        "| Ejecución | Correctas | Entregadas originales | Reales | Precisión | Cobertura |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in report["classification_runs"]:
        overall = run["metrics"]["overall"]
        lines.append(
            f"| {run['run_name']} | {overall['correct_photos']} | {overall['predicted_photos']} | "
            f"{overall['target_photos']} | {_percent(overall['precision'])} | {_percent(overall['recall'])} |"
        )
    lines.extend(["", "### Resultado por identidad", ""])
    for run in report["classification_runs"]:
        lines.extend([
            f"#### {run['run_name']}",
            "",
            "| Identidad | TP | FP | FN | Precisión | Cobertura |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for identity, values in run["metrics"]["by_identity"].items():
            lines.append(
                f"| {identity} | {values['tp']} | {values['fp']} | {values['fn']} | "
                f"{_percent(values['precision'])} | {_percent(values['recall'])} |"
            )
        lines.extend(["", "Errores y omisiones exactos:", ""])
        errors = run["metrics"]["errors"]
        if not errors:
            lines.append("- Ninguno.")
        else:
            for error in errors:
                lines.append(
                    f"- `{error['file']}` — esperado: `{', '.join(error['expected']) or 'sin identidad'}`; "
                    f"resultado: `{error['predicted'] or 'omitida'}`; tipo: `{error['error']}`."
                )
        if run["unknown_deliveries"]:
            lines.extend(["", "Archivos auxiliares fuera del manifiesto:", ""])
            for item in run["unknown_deliveries"]:
                lines.append(f"- `{item['file']}` en `{item['identity']}`.")
        lines.append("")

    diagnostics = report["representation_diagnostics"]
    lines.extend([
        "## Diagnóstico separado por representación",
        "",
        "La predicción de esta sección usa solamente la referencia natural y el umbral directo `0.28`. "
        "No sustituye la ejecución real; sirve para explicar distancias y detectar dónde se rompe la cobertura.",
        "",
        "| Ruta | Decodificadas | Con rostro | Rostros | Precisión directa | Cobertura directa |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for route in ("preview", "fullraw"):
        summary = diagnostics["summaries"][route]
        overall = summary["direct_natural_reference"]["overall"]
        lines.append(
            f"| {route} | {summary['decoded']} | {summary['with_faces']} | {summary['total_faces']} | "
            f"{_percent(overall['precision'])} | {_percent(overall['recall'])} |"
        )
    lines.extend([
        "",
        "## Trazabilidad por fotografía",
        "",
        "Cada fila muestra identidad real, cantidad de rostros, mejor distancia a referencia natural y "
        "la menor distancia a la galería de verdad leave-one-out. Las cajas completas, confianza, posición, "
        "distancias a ambas referencias y a cada identidad están en el JSON.",
        "",
        "| Foto | Verdad | Preview: rostros / ref / galería | Full RAW: rostros / ref / galería |",
        "|---|---|---|---|",
    ])
    for photo in diagnostics["photos"]:
        truth = ", ".join(photo["target_identities"]) or "SIN OBJETIVO"
        route_cells = []
        for route in ("preview", "fullraw"):
            data = photo["routes"][route]
            expected = photo["target_identities"][0] if photo["target_identities"] else None
            ref_distance = None
            gallery_distance = None
            if data["faces"]:
                if expected:
                    ref_distance = min(
                        face["distances_to_references"][expected]["natural_reference"]
                        for face in data["faces"]
                        if face["distances_to_references"][expected]["natural_reference"] is not None
                    )
                    gallery_values = [
                        face["distances_to_truth_gallery"][expected]["min_distance"]
                        for face in data["faces"]
                        if face["distances_to_truth_gallery"][expected]["min_distance"] is not None
                    ]
                    gallery_distance = min(gallery_values) if gallery_values else None
                else:
                    values = [
                        info["min_distance"]
                        for face in data["faces"]
                        for info in face["distances_to_truth_gallery"].values()
                        if info["min_distance"] is not None
                    ]
                    gallery_distance = min(values) if values else None
            route_cells.append(
                f"{data['face_count']} / {ref_distance if ref_distance is not None else 'N/A'} / "
                f"{gallery_distance if gallery_distance is not None else 'N/A'}"
            )
        lines.append(f"| `{photo['file']}` | {truth} | {route_cells[0]} | {route_cells[1]} |")
    lines.extend([
        "",
        "## Interpretación permitida",
        "",
        "- Los resultados de clasificación se calculan desde las carpetas/reportes reales contra el manifiesto.",
        "- Las rutas preview y Full RAW se miden por separado y sus embeddings no se combinan.",
        "- La galería leave-one-out es diagnóstico de cohesión potencial, no una simulación de la galería de producción.",
        "- El JSON no guarda embeddings; conserva únicamente medidas y distancias necesarias para reproducir conclusiones.",
        "- Este módulo mide y explica. No cambia umbrales ni decisiones del clasificador.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest.resolve())
    diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8"))
    report = build_report(manifest, diagnostics)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "MODULE_1_CR3_EVALUATION.json"
    markdown_path = args.output_dir / "MODULE_1_CR3_EVALUATION.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
