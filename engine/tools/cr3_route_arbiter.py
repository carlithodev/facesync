"""Arbitraje aislado de decisiones preview y Full RAW para CR3.

Esta capa no calcula embeddings ni vuelve a clasificar. Recibe las decisiones
independientes de las dos rutas, relaciona rostros por geometria y decide si la
evidencia Full RAW puede agregar una identidad sin reemplazar la decision base.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from tools.cr3_reference_selector import match_faces_by_geometry


def _resolved(value: Any) -> Path:
    return Path(value).resolve(strict=False)


def _safe_float(value: Any, default: float = 999.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _real_face(face: Dict[str, Any]) -> bool:
    return bool(face.get("embedding")) and _safe_float(
        face.get("face_confidence"), 1.0
    ) > 0.0


def _geometry_face(face: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibilidad: ausencia historica no equivale a confianza cero."""
    if "face_confidence" in face:
        return face
    compatible = dict(face)
    compatible["face_confidence"] = 1.0
    return compatible


def _resolved_mapping(mapping: Mapping[Any, Any]) -> Dict[Path, Any]:
    return {_resolved(path): value for path, value in (mapping or {}).items()}


def _folder(person: Mapping[str, Any]) -> str:
    return str(person.get("folder_name", ""))


def _display(person: Mapping[str, Any]) -> str:
    return str(person.get("display_name") or person.get("folder_name") or "")


def _conflicts_by_face(
    conflicts: Iterable[Mapping[str, Any]],
) -> Dict[Tuple[Path, int], Mapping[str, Any]]:
    result: Dict[Tuple[Path, int], Mapping[str, Any]] = {}
    for conflict in conflicts or []:
        path = conflict.get("image_path")
        if path is None:
            continue
        result[(_resolved(path), int(conflict.get("face_index", 0)))] = conflict
    return result


def _rescues_by_identity(
    rescues: Iterable[Mapping[str, Any]],
) -> Dict[Tuple[Path, str], Mapping[str, Any]]:
    result: Dict[Tuple[Path, str], Mapping[str, Any]] = {}
    for rescue in rescues or []:
        path = rescue.get("image_path")
        if path is None:
            continue
        name = str(rescue.get("person_display_name", ""))
        result[(_resolved(path), name)] = rescue
    return result


def _route_decisions(
    path: Path,
    *,
    matches: Mapping[Path, List[Dict[str, Any]]],
    confirmed: Mapping[Path, List[Dict[str, Any]]],
    conflicts: Mapping[Tuple[Path, int], Mapping[str, Any]],
    rescues: Mapping[Tuple[Path, str], Mapping[str, Any]],
    review_threshold: float,
    min_gallery_support: int,
) -> Tuple[Dict[int, Dict[str, Any]], set[str]]:
    path = _resolved(path)
    confirmed_people = list(confirmed.get(path) or [])
    confirmed_by_folder = {
        _folder(person): person for person in confirmed_people if _folder(person)
    }
    candidates_by_face: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for match in matches.get(path) or []:
        distance = _safe_float(match.get("distance"))
        if distance > review_threshold:
            continue
        person = match.get("person") or {}
        folder = _folder(person)
        if not folder:
            continue
        face_index = int(match.get("face_index", 0))
        previous = candidates_by_face.setdefault(face_index, {}).get(folder)
        if previous is None or distance < _safe_float(previous.get("distance")):
            candidates_by_face[face_index][folder] = match

    decisions: Dict[int, Dict[str, Any]] = {}
    located_confirmed: set[str] = set()
    face_indices = set(candidates_by_face)
    face_indices.update(
        face_index
        for conflict_path, face_index in conflicts
        if conflict_path == path
    )
    for face_index in sorted(face_indices):
        candidates = sorted(
            candidates_by_face.get(face_index, {}).values(),
            key=lambda item: (
                _safe_float(item.get("distance")),
                _folder(item.get("person") or {}).casefold(),
            ),
        )
        confirmed_candidates = [
            candidate
            for candidate in candidates
            if _folder(candidate.get("person") or {}) in confirmed_by_folder
        ]
        conflict = conflicts.get((path, face_index))
        if len({_folder(item.get("person") or {}) for item in confirmed_candidates}) > 1:
            decisions[face_index] = {
                "state": "conflict",
                "folders": sorted({
                    _folder(item.get("person") or {})
                    for item in confirmed_candidates
                }),
            }
            continue
        if confirmed_candidates:
            chosen = confirmed_candidates[0]
            state = "confirmed"
            located_confirmed.add(_folder(chosen.get("person") or {}))
        elif conflict is not None:
            decisions[face_index] = {
                "state": "conflict",
                "folders": sorted({
                    _folder(item.get("person") or {})
                    for item in conflict.get("candidates") or []
                    if _folder(item.get("person") or {})
                }),
            }
            continue
        elif candidates:
            chosen = candidates[0]
            state = "review"
        else:
            continue

        person = chosen.get("person") or {}
        folder = _folder(person)
        other_distances = [
            _safe_float(candidate.get("distance"))
            for candidate in candidates
            if _folder(candidate.get("person") or {}) != folder
        ]
        distance = _safe_float(chosen.get("distance"))
        reference_margin = (
            min(other_distances) - distance if other_distances else None
        )
        bootstrap_supporters = int(chosen.get("bootstrap_supporters", 0) or 0)
        rescue = rescues.get((path, _display(person)))
        gallery_supporters = max(
            bootstrap_supporters,
            int((rescue or {}).get("supporter_count", 0) or 0),
        )
        decisions[face_index] = {
            "state": state,
            "person": person,
            "folder": folder,
            "distance": distance,
            "reference_margin": reference_margin,
            "match_source": str(chosen.get("match_source", "")),
            "gallery_supporters": gallery_supporters,
            "gallery_supported": gallery_supporters >= min_gallery_support,
        }

    return decisions, set(confirmed_by_folder) - located_confirmed


def arbitrate_cr3_routes(
    *,
    image_paths: Iterable[Path],
    preview_matches: Mapping[Path, List[Dict[str, Any]]],
    preview_faces: Mapping[Path, List[Dict[str, Any]]],
    preview_sizes: Mapping[Path, Tuple[int, int]],
    preview_confirmed: Mapping[Path, List[Dict[str, Any]]],
    preview_conflicts: Iterable[Mapping[str, Any]],
    preview_rescues: Iterable[Mapping[str, Any]],
    fullraw_matches: Mapping[Path, List[Dict[str, Any]]],
    fullraw_faces: Mapping[Path, List[Dict[str, Any]]],
    fullraw_sizes: Mapping[Path, Tuple[int, int]],
    fullraw_confirmed: Mapping[Path, List[Dict[str, Any]]],
    fullraw_conflicts: Iterable[Mapping[str, Any]],
    fullraw_rescues: Iterable[Mapping[str, Any]],
    secure_threshold: float,
    review_threshold: float,
    identity_margin: float,
    geometry_min_iou: float,
    geometry_min_margin: float,
    min_gallery_support: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Coordina ambas rutas sin reemplazar una asignacion preview segura."""
    cr3_paths = sorted(
        {_resolved(path) for path in image_paths if Path(path).suffix.lower() == ".cr3"},
        key=lambda path: str(path).casefold(),
    )
    stats: Dict[str, Any] = {
        "enabled": bool(cr3_paths),
        "cr3_photos": len(cr3_paths),
        "fullraw_confirmed_faces": 0,
        "agreements": 0,
        "preview_assignments_preserved": 0,
        "rescues_accepted": 0,
        "rescues_by_consensus": 0,
        "rescues_fullraw_only": 0,
        "blocked_contradictions": 0,
        "blocked_geometry": 0,
        "blocked_margin": 0,
        "blocked_evidence": 0,
    }
    if not cr3_paths:
        return [], [], stats

    preview_matches_r = _resolved_mapping(preview_matches)
    preview_faces_r = _resolved_mapping(preview_faces)
    preview_sizes_r = _resolved_mapping(preview_sizes)
    preview_confirmed_r = _resolved_mapping(preview_confirmed)
    fullraw_matches_r = _resolved_mapping(fullraw_matches)
    fullraw_faces_r = _resolved_mapping(fullraw_faces)
    fullraw_sizes_r = _resolved_mapping(fullraw_sizes)
    fullraw_confirmed_r = _resolved_mapping(fullraw_confirmed)
    preview_conflicts_r = _conflicts_by_face(preview_conflicts)
    fullraw_conflicts_r = _conflicts_by_face(fullraw_conflicts)
    preview_rescues_r = _rescues_by_identity(preview_rescues)
    fullraw_rescues_r = _rescues_by_identity(fullraw_rescues)

    accepted: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    def record(
        path: Path,
        full_index: int,
        decision: Dict[str, Any],
        *,
        status: str,
        reason: str,
        preview_index: Optional[int] = None,
        preview_decision: Optional[Dict[str, Any]] = None,
        geometry: Optional[Dict[str, Any]] = None,
    ) -> None:
        diagnostics.append({
            "foto": str(path),
            "rostro_fullraw": full_index + 1,
            "rostro_preview": preview_index + 1 if preview_index is not None else None,
            "alumno_fullraw": _display(decision.get("person") or {}),
            "alumno_preview": (
                _display((preview_decision or {}).get("person") or {}) or None
            ),
            "estado": status,
            "motivo": reason,
            "distancia_fullraw": round(float(decision["distance"]), 6),
            "margen_fullraw": (
                round(float(decision["reference_margin"]), 6)
                if decision.get("reference_margin") is not None else None
            ),
            "soportes_galeria_fullraw": int(decision.get("gallery_supporters", 0)),
            "distancia_preview": (
                round(float(preview_decision["distance"]), 6)
                if preview_decision and preview_decision.get("distance") is not None
                else None
            ),
            "margen_preview": (
                round(float(preview_decision["reference_margin"]), 6)
                if preview_decision
                and preview_decision.get("reference_margin") is not None
                else None
            ),
            "geometria": geometry,
        })

    for path in cr3_paths:
        preview_path_faces = list(preview_faces_r.get(path) or [])
        fullraw_path_faces = list(fullraw_faces_r.get(path) or [])
        preview_decisions, preview_unlocated = _route_decisions(
            path,
            matches=preview_matches_r,
            confirmed=preview_confirmed_r,
            conflicts=preview_conflicts_r,
            rescues=preview_rescues_r,
            review_threshold=review_threshold,
            min_gallery_support=min_gallery_support,
        )
        fullraw_decisions, _fullraw_unlocated = _route_decisions(
            path,
            matches=fullraw_matches_r,
            confirmed=fullraw_confirmed_r,
            conflicts=fullraw_conflicts_r,
            rescues=fullraw_rescues_r,
            review_threshold=review_threshold,
            min_gallery_support=min_gallery_support,
        )
        geometry = match_faces_by_geometry(
            [_geometry_face(face) for face in preview_path_faces],
            tuple(preview_sizes_r.get(path) or (0, 0)),
            [_geometry_face(face) for face in fullraw_path_faces],
            tuple(fullraw_sizes_r.get(path) or (0, 0)),
            min_iou=geometry_min_iou,
            min_margin=geometry_min_margin,
        )
        pairs_by_fullraw = {
            int(pair["fullraw_index"]): pair
            for pair in geometry.get("pairs") or []
            if pair.get("accepted")
        }
        real_preview = [index for index, face in enumerate(preview_path_faces) if _real_face(face)]
        real_fullraw = [index for index, face in enumerate(fullraw_path_faces) if _real_face(face)]

        for full_index, full_decision in sorted(fullraw_decisions.items()):
            if full_decision.get("state") != "confirmed":
                continue
            stats["fullraw_confirmed_faces"] += 1
            folder = str(full_decision.get("folder", ""))
            margin = full_decision.get("reference_margin")
            margin_ok = margin is None or float(margin) >= identity_margin
            evidence_ok = (
                float(full_decision.get("distance", 999)) <= secure_threshold
                or bool(full_decision.get("gallery_supported"))
            )
            if not evidence_ok:
                stats["blocked_evidence"] += 1
                record(
                    path, full_index, full_decision,
                    status="bloqueada", reason="evidencia_fullraw_insuficiente",
                )
                continue
            if not margin_ok and not full_decision.get("gallery_supported"):
                stats["blocked_margin"] += 1
                record(
                    path, full_index, full_decision,
                    status="bloqueada", reason="margen_fullraw_insuficiente",
                )
                continue

            pair = pairs_by_fullraw.get(full_index)
            preview_index: Optional[int] = None
            geometry_summary: Optional[Dict[str, Any]] = None
            if pair is not None:
                preview_index = int(pair["preview_index"])
                geometry_summary = {
                    "transformacion": geometry.get("transform", "identity"),
                    "iou": round(float(pair.get("iou", 0.0)), 6),
                    "margen": round(float(pair.get("margin", 0.0)), 6),
                }
            elif not real_preview and real_fullraw == [full_index]:
                geometry_summary = {
                    "transformacion": None,
                    "iou": None,
                    "margen": None,
                    "caso": "rostro_unico_solo_fullraw",
                }
            else:
                stats["blocked_geometry"] += 1
                record(
                    path, full_index, full_decision,
                    status="bloqueada", reason="sin_correspondencia_geometrica_segura",
                    geometry={
                        "transformacion": geometry.get("transform", "identity"),
                        "iou": None,
                        "margen": None,
                    },
                )
                continue

            preview_decision = (
                preview_decisions.get(preview_index)
                if preview_index is not None else None
            )
            if preview_decision and preview_decision.get("state") == "conflict":
                stats["blocked_contradictions"] += 1
                record(
                    path, full_index, full_decision,
                    status="bloqueada", reason="conflicto_preview_existente",
                    preview_index=preview_index,
                    preview_decision=preview_decision,
                    geometry=geometry_summary,
                )
                continue

            preview_folder = str((preview_decision or {}).get("folder", ""))
            if preview_decision and preview_decision.get("state") == "confirmed":
                if preview_folder != folder:
                    stats["blocked_contradictions"] += 1
                    stats["preview_assignments_preserved"] += 1
                    record(
                        path, full_index, full_decision,
                        status="bloqueada", reason="asignacion_preview_segura_inmutable",
                        preview_index=preview_index,
                        preview_decision=preview_decision,
                        geometry=geometry_summary,
                    )
                    continue
                stats["agreements"] += 1
                stats["preview_assignments_preserved"] += 1
                record(
                    path, full_index, full_decision,
                    status="conservada", reason="coincidencia_entre_rutas",
                    preview_index=preview_index,
                    preview_decision=preview_decision,
                    geometry=geometry_summary,
                )
                continue

            if preview_unlocated:
                stats["preview_assignments_preserved"] += 1
                if folder in preview_unlocated:
                    stats["agreements"] += 1
                    record(
                        path, full_index, full_decision,
                        status="conservada",
                        reason="coincidencia_con_propietario_preview_no_localizado",
                        preview_index=preview_index,
                        preview_decision=preview_decision,
                        geometry=geometry_summary,
                    )
                else:
                    stats["blocked_contradictions"] += 1
                    record(
                        path, full_index, full_decision,
                        status="bloqueada",
                        reason="propietario_preview_sin_rostro_localizable",
                        preview_index=preview_index,
                        preview_decision=preview_decision,
                        geometry=geometry_summary,
                    )
                continue

            reason = "rescate_solo_fullraw"
            if preview_decision and preview_decision.get("state") == "review":
                if preview_folder == folder:
                    reason = "consenso_preview_fullraw"
                    stats["rescues_by_consensus"] += 1
                else:
                    preview_margin = preview_decision.get("reference_margin")
                    preview_claim_is_clear = (
                        preview_margin is None
                        or float(preview_margin) >= identity_margin
                    )
                    if preview_claim_is_clear:
                        stats["blocked_contradictions"] += 1
                        record(
                            path, full_index, full_decision,
                            status="bloqueada", reason="rutas_proponen_identidades_distintas",
                            preview_index=preview_index,
                            preview_decision=preview_decision,
                            geometry=geometry_summary,
                        )
                        continue
                    reason = "fullraw_supera_preview_ambiguo"
            if reason == "rescate_solo_fullraw":
                stats["rescues_fullraw_only"] += 1

            accepted.append({
                "path": path,
                "person": full_decision["person"],
                "preview_face_index": preview_index,
                "fullraw_face_index": full_index,
                "reason": reason,
                "distance": float(full_decision["distance"]),
                "identity_margin": full_decision.get("reference_margin"),
                "gallery_supporters": int(full_decision.get("gallery_supporters", 0)),
                "match_source": full_decision.get("match_source", ""),
            })
            stats["rescues_accepted"] += 1
            record(
                path, full_index, full_decision,
                status="rescatada", reason=reason,
                preview_index=preview_index,
                preview_decision=preview_decision,
                geometry=geometry_summary,
            )

    return accepted, diagnostics, stats
