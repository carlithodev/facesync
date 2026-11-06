"""Genera los artefactos reproducibles del Módulo 2 desde mediciones CR3."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _fmt(value: Any, digits: int = 4) -> str:
    return "N/A" if value is None else f"{float(value):.{digits}f}"


def _pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.1f}%"


def build_module2_report(diagnostics: dict[str, Any]) -> dict[str, Any]:
    analysis = diagnostics.get("representation_analysis")
    if not isinstance(analysis, dict):
        raise ValueError("Las mediciones no contienen representation_analysis del Módulo 2.")

    omissions = []
    for photo in diagnostics.get("photos") or []:
        if not photo.get("target_identities"):
            continue
        identity = photo["target_identities"][0]
        route_rows = {}
        for route in ("preview", "fullraw"):
            faces = photo["routes"][route].get("faces") or []
            if not faces:
                route_rows[route] = {
                    "natural_reference_distance": None,
                    "truth_gallery_min": None,
                    "diagnosis": "no_face",
                }
                continue
            face = min(
                faces,
                key=lambda item: item["distances_to_references"][identity]["natural_reference"]
                if item["distances_to_references"][identity]["natural_reference"] is not None
                else 999.0,
            )
            reference = face["distances_to_references"][identity]["natural_reference"]
            gallery = face["distances_to_truth_gallery"][identity]["min_distance"]
            if float(face.get("confidence") or 0) <= 0:
                diagnosis = "fallback_without_detected_face"
            elif reference is not None and reference <= 0.28:
                diagnosis = "direct_reference_support"
            elif gallery is not None and gallery <= 0.28:
                diagnosis = "reference_limited_but_identity_coherent"
            else:
                diagnosis = "hard_for_route"
            route_rows[route] = {
                "natural_reference_distance": reference,
                "truth_gallery_min": gallery,
                "diagnosis": diagnosis,
            }
        omissions.append({
            "file": photo["file"],
            "identity": identity,
            "preview": route_rows["preview"],
            "fullraw": route_rows["fullraw"],
        })

    corresponding = analysis["cross_route"]["corresponding_photos"]
    most_changed = sorted(
        corresponding,
        key=lambda row: float(row["embedding_distance_preview_vs_fullraw"]),
        reverse=True,
    )
    sequence_preferences = {
        row["preferred_route_by_internal_coherence"]
        for row in analysis["sequence_comparison"]
        if row["preferred_route_by_internal_coherence"] in {"preview", "fullraw"}
    }
    strategy = (
        "independent_route_selection_by_sequence"
        if len(sequence_preferences) > 1
        else "single_route_candidate_requires_more_people"
    )
    return {
        "schema_version": 1,
        "module": 2,
        "purpose": "Diagnóstico comparativo de preview y Full RAW CR3",
        "source_measurements": {
            "photo_count": diagnostics.get("photo_count"),
            "model_name": diagnostics.get("model_name"),
            "detector_backend": diagnostics.get("detector_backend"),
            "direct_threshold_unchanged": diagnostics.get("direct_threshold"),
        },
        "within_route": analysis["within_route"],
        "cross_route": analysis["cross_route"],
        "sequence_comparison": analysis["sequence_comparison"],
        "most_changed_photos": most_changed,
        "omission_diagnosis": omissions,
        "decision": {
            "strategy": strategy,
            "selected_global_route": None,
            "reason": (
                "Las secuencias no favorecen de forma uniforme a una sola representación; "
                "preview y Full RAW deben conservar espacios y decisiones independientes."
                if strategy == "independent_route_selection_by_sequence"
                else "La muestra actual no justifica reemplazar globalmente una ruta; se requieren más identidades."
            ),
            "parameter_changes_authorized": False,
            "production_behavior_changed": False,
        },
        "limitations": analysis.get("limitations") or [],
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Módulo 2 — Diagnóstico de representaciones CR3",
        "",
        "## Alcance",
        "",
        f"- Fotografías medidas: `{report['source_measurements']['photo_count']}`.",
        f"- Modelo: `{report['source_measurements']['model_name']}`.",
        f"- Detector: `{report['source_measurements']['detector_backend']}`.",
        f"- Umbral observado, sin modificar: `{report['source_measurements']['direct_threshold_unchanged']}`.",
        "- Los embeddings permanecieron en memoria y no forman parte de los artefactos.",
        "",
        "## Distribuciones dentro de cada representación",
        "",
        "Las parejas de la misma persona, personas diferentes y controles sin persona se reportan por separado.",
        "",
        "| Ruta | Clase | N | Mín. | Mediana | P90 | Máx. | Media |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for route in ("preview", "fullraw"):
        summary = report["within_route"][route]["summary"]
        detected_summary = summary["detected_faces_only"]
        for pair_class, label in (
            ("same_identity", "Misma persona"),
            ("different_identity", "Personas diferentes"),
            ("no_target_control", "Control sin persona"),
        ):
            dist = detected_summary["distributions"][pair_class]
            lines.append(
                f"| {route} | {label} | {dist['count']} | {_fmt(dist['min'])} | "
                f"{_fmt(dist['median'])} | {_fmt(dist['p90'])} | {_fmt(dist['max'])} | {_fmt(dist['mean'])} |"
            )
        separation = detected_summary["human_identity_separation"]
        lines.extend([
            "",
            f"- `{route}`: AUC diagnóstica `{_fmt(separation['auc_lower_is_match'])}`; "
            f"aceptación de pares verdaderos a 0.28 `{_pct(separation['true_accept_rate_at_current_threshold'])}`; "
            f"aceptación de pares humanos diferentes `{_pct(separation['false_accept_rate_at_current_threshold'])}`; "
            f"pares excluidos por respaldo sin detección `{summary['pairs_involving_fallback']}`.",
            "",
        ])

    lines.extend([
        "### Pares de personas distintas más cercanos",
        "",
        "Esta tabla permite localizar solapamientos reales entre identidades humanas; los controles sin persona no se incluyen.",
        "",
        "| Ruta | Foto A | Foto B | Distancia | Dentro de 0.28 |",
        "|---|---|---|---:|---|",
    ])
    for route in ("preview", "fullraw"):
        pairs = [
            pair for pair in report["within_route"][route]["pairs"]
            if pair["pair_class"] == "different_identity" and pair.get("both_detected_faces", False)
        ]
        for pair in sorted(pairs, key=lambda item: float(item["distance"]))[:3]:
            lines.append(
                f"| {route} | `{pair['left_file']}` ({pair['left_identity']}) | "
                f"`{pair['right_file']}` ({pair['right_identity']}) | {_fmt(pair['distance'])} | "
                f"{'sí' if float(pair['distance']) <= 0.28 else 'no'} |"
            )

    cross = report["cross_route"]["summary"]
    lines.extend([
        "## Correspondencia preview contra Full RAW",
        "",
        f"- Fotografías correspondientes: `{cross['corresponding_count']}`.",
        f"- Distancia mediana entre representaciones: `{_fmt(cross['corresponding_embedding_distance']['median'])}`.",
        f"- Distancia P90 entre representaciones: `{_fmt(cross['corresponding_embedding_distance']['p90'])}`.",
        f"- IoU mediana de caja facial: `{_fmt(cross['bbox_iou']['median'])}`.",
        f"- Desplazamiento mediano del centro facial: `{_fmt(cross['bbox_center_shift']['median'])}`.",
        f"- Cambios de orientación de imagen: `{cross['orientation_mismatch_count']}`.",
        f"- Respaldos sin rostro detectado en preview: `{cross['preview_fallback_count']}`.",
        f"- Respaldos sin rostro detectado en Full RAW: `{cross['fullraw_fallback_count']}`.",
        "",
        "### Fotografías con mayor cambio entre rutas",
        "",
        "| Foto | Verdad | Distancia cruzada | IoU caja | Detección P/F | Preferencia por galería |",
        "|---|---|---:|---:|---|---|",
    ])
    for row in report["most_changed_photos"][:12]:
        lines.append(
            f"| `{row['file']}` | {row['identity'] or 'SIN OBJETIVO'} | "
            f"{_fmt(row['embedding_distance_preview_vs_fullraw'])} | {_fmt(row['bbox_iou_normalized'])} | "
            f"{'sí' if row['face_detected_preview'] else 'respaldo'}/"
            f"{'sí' if row['face_detected_fullraw'] else 'respaldo'} | "
            f"{row['preferred_route_by_gallery']} |"
        )

    mismatches = [row for row in report["cross_route"]["corresponding_photos"] if not row["orientation_match"]]
    lines.extend([
        "",
        "### Cambios de orientación o caja facial",
        "",
        "| Foto | Preview | Full RAW | IoU caja | Desplazamiento centro | Observación |",
        "|---|---|---|---:|---:|---|",
    ])
    if not mismatches:
        lines.append("| Ninguna | — | — | — | — | — |")
    for row in mismatches:
        observation = (
            "preview usó respaldo de imagen completa"
            if not row["face_detected_preview"]
            else "orientación distinta con rostro detectado"
        )
        lines.append(
            f"| `{row['file']}` | {row['orientation_preview']} | {row['orientation_fullraw']} | "
            f"{_fmt(row['bbox_iou_normalized'])} | {_fmt(row['bbox_center_shift_normalized'])} | {observation} |"
        )

    lines.extend([
        "",
        "## Sensibilidad a postura, iluminación y tamaño facial",
        "",
        "| Ruta | Corr. luz/distancia | Corr. tamaño/distancia | Misma postura N/mediana | Postura distinta N/mediana | Exposición extrema N/mediana |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for route in ("preview", "fullraw"):
        sensitivity = report["within_route"][route]["condition_sensitivity"]
        same_pose = sensitivity["pose"]["same_tag"]
        changed_pose = sensitivity["pose"]["different_tag"]
        extreme = sensitivity["illumination"]["involves_annotated_extreme"]
        lines.append(
            f"| {route} | {_fmt(sensitivity['correlations']['distance_vs_luminance_gap'])} | "
            f"{_fmt(sensitivity['correlations']['distance_vs_face_area_log_gap'])} | "
            f"{same_pose['count']}/{_fmt(same_pose['median'])} | "
            f"{changed_pose['count']}/{_fmt(changed_pose['median'])} | "
            f"{extreme['count']}/{_fmt(extreme['median'])} |"
        )

    lines.extend([
        "",
        "## Resultado por secuencia",
        "",
        "La ruta preferida se determina por menor mediana de distancias internas verdaderas; no es una decisión de producción.",
        "",
        "| Secuencia | Pares preview | Mediana preview | Pares Full RAW | Mediana Full RAW | Resultado |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for row in report["sequence_comparison"]:
        lines.append(
            f"| {row['sequence']} | {row['preview']['count']} | {_fmt(row['preview']['median'])} | "
            f"{row['fullraw']['count']} | {_fmt(row['fullraw']['median'])} | "
            f"{row['preferred_route_by_internal_coherence']} |"
        )

    diagnosis_counts: dict[str, dict[str, int]] = {
        route: {} for route in ("preview", "fullraw")
    }
    for row in report["omission_diagnosis"]:
        for route in ("preview", "fullraw"):
            diagnosis = row[route]["diagnosis"]
            diagnosis_counts[route][diagnosis] = diagnosis_counts[route].get(diagnosis, 0) + 1
    lines.extend([
        "",
        "## Diagnóstico de las omisiones",
        "",
        "`reference_limited_but_identity_coherent` significa que la referencia natural queda fuera de 0.28, "
        "pero la fotografía sí forma un grupo coherente con otras imágenes reales de la misma persona.",
        "",
        "| Ruta | Apoyo directo | Limitada por referencia | Difícil incluso con galería | Respaldo sin detección |",
        "|---|---:|---:|---:|---:|",
    ])
    for route in ("preview", "fullraw"):
        counts = diagnosis_counts[route]
        lines.append(
            f"| {route} | {counts.get('direct_reference_support', 0)} | "
            f"{counts.get('reference_limited_but_identity_coherent', 0)} | "
            f"{counts.get('hard_for_route', 0) + counts.get('no_face', 0)} | "
            f"{counts.get('fallback_without_detected_face', 0)} |"
        )

    lines.extend([
        "",
        "## Decisión documentada",
        "",
        f"- Estrategia: `{report['decision']['strategy']}`.",
        f"- Ruta global seleccionada: `{report['decision']['selected_global_route'] or 'ninguna'}`.",
        f"- Motivo: {report['decision']['reason']}",
        "- Preview y Full RAW permanecen separados; sus embeddings no se mezclan ni se promedian.",
        "- Este módulo no autoriza ajustes de umbral ni cambios en la clasificación.",
        "",
        "## Limitaciones",
        "",
    ])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _write_matrix(path: Path, labels: list[dict[str, Any]], matrix: list[list[Any]]) -> None:
    names = [
        f"{item['file']}#face{item['face_index']}:{item.get('identity') or 'NO_TARGET'}"
        for item in labels
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample", *names])
        for name, row in zip(names, matrix):
            writer.writerow([name, *row])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8"))
    report = build_module2_report(diagnostics)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "MODULE_2_CR3_REPRESENTATIONS.json"
    markdown_path = args.output_dir / "MODULE_2_CR3_REPRESENTATIONS.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")

    for route in ("preview", "fullraw"):
        data = report["within_route"][route]
        _write_matrix(
            args.output_dir / f"MODULE_2_{route.upper()}_MATRIX.csv",
            data["labels"],
            data["distance_matrix"],
        )
    cross = report["cross_route"]
    cross_path = args.output_dir / "MODULE_2_PREVIEW_VS_FULLRAW_MATRIX.csv"
    row_names = [
        f"{item['file']}#face{item['face_index']}:{item.get('identity') or 'NO_TARGET'}"
        for item in cross["preview_labels"]
    ]
    column_names = [
        f"{item['file']}#face{item['face_index']}:{item.get('identity') or 'NO_TARGET'}"
        for item in cross["fullraw_labels"]
    ]
    with cross_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["preview\\fullraw", *column_names])
        for name, row in zip(row_names, cross["distance_matrix"]):
            writer.writerow([name, *row])

    for path in (json_path, markdown_path, cross_path):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
