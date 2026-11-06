"""Arranque seguro y aislado de galerias para archivos CR3.

Este modulo no detecta rostros, no genera embeddings y no asigna fotografias
por una busqueda amplia. Recibe evidencia ya creada por RetinaFace/ArcFace,
forma grupos coherentes en una sola representacion y devuelve propuestas que
la capa de decision existente debe resolver globalmente.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


Face = Dict[str, Any]
Node = Dict[str, Any]
Distance = Callable[[Iterable[float], Iterable[float]], float]


def _resolved(path: Any) -> Path:
    return Path(path).resolve(strict=False)


def _safe_float(value: Any, default: float = 999.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _real_face(face: Face) -> bool:
    return bool(face.get("embedding")) and _safe_float(
        face.get("face_confidence"), 0.0
    ) > 0.0


def _folder(reference: Dict[str, Any]) -> str:
    person = reference.get("person") or {}
    return str(person.get("folder_name") or person.get("display_name") or "")


def _face_side(face: Face) -> Optional[float]:
    area = face.get("facial_area") or {}
    width = _safe_float(area.get("w"), 0.0)
    height = _safe_float(area.get("h"), 0.0)
    if width <= 0.0 or height <= 0.0:
        return None
    return math.sqrt(width * height)


def _reference_face_side(reference: Dict[str, Any]) -> Optional[float]:
    faces = list(reference.get("candidate_faces") or [])
    if not faces:
        return None
    return _face_side(faces[0])


def _scale_compatible(
    face_side: Optional[float],
    reference_side: Optional[float],
    max_log_gap: float,
) -> bool:
    if face_side is None or reference_side is None:
        return True
    return abs(math.log(face_side / reference_side)) <= max_log_gap


def _unique_gallery_entries(gallery: Dict[str, Any]) -> List[Tuple[list, Path]]:
    embeddings = list(
        gallery.get("anchor_embeddings") or gallery.get("embeddings") or []
    )
    paths = list(gallery.get("anchor_paths") or gallery.get("paths") or [])
    entries: List[Tuple[list, Path]] = []
    for index, embedding in enumerate(embeddings):
        if not embedding:
            continue
        path = _resolved(paths[index]) if index < len(paths) else Path()
        entries.append((embedding, path))
    return entries


def _cluster_metrics(nodes: List[Node], distance: Distance) -> Dict[str, float]:
    values = [
        distance(left["embedding"], right["embedding"])
        for index, left in enumerate(nodes)
        for right in nodes[index + 1 :]
        if left["path"] != right["path"]
    ]
    return {
        "median": statistics.median(values) if values else 999.0,
        "maximum": max(values) if values else 999.0,
    }


def _rank_medoids(nodes: List[Node], distance: Distance) -> List[Node]:
    ranked = []
    for node in nodes:
        peers = [peer for peer in nodes if peer["path"] != node["path"]]
        average = (
            statistics.fmean(
                distance(node["embedding"], peer["embedding"])
                for peer in peers
            )
            if peers
            else 999.0
        )
        ranked.append(
            (average, str(node["path"]).casefold(), node["face_index"], node)
        )
    return [item[-1] for item in sorted(ranked, key=lambda item: item[:-1])]


def _coherent_star(
    seed: Node,
    nodes: List[Node],
    *,
    distance: Distance,
    secure_threshold: float,
) -> List[Node]:
    """Forma un nucleo estricto, con una sola cara por fotografia."""
    best_by_path: Dict[Path, Tuple[float, Node]] = {}
    for node in nodes:
        value = distance(seed["embedding"], node["embedding"])
        if value > secure_threshold:
            continue
        previous = best_by_path.get(node["path"])
        if previous is None or (value, node["face_index"]) < (
            previous[0],
            previous[1]["face_index"],
        ):
            best_by_path[node["path"]] = (value, node)
    group = [item[1] for item in best_by_path.values()]
    if len(group) < 2:
        return group
    medoid = _rank_medoids(group, distance)[0]
    return [
        node
        for node in group
        if distance(medoid["embedding"], node["embedding"])
        <= secure_threshold
    ]


def _other_gallery_distance(
    node: Node,
    target_folder: str,
    galleries: Dict[str, Dict[str, Any]],
    distance: Distance,
) -> Optional[float]:
    values = [
        distance(node["embedding"], embedding)
        for folder, gallery in galleries.items()
        if folder != target_folder
        for embedding, _path in _unique_gallery_entries(gallery)
    ]
    return min(values) if values else None


def build_cr3_gallery_bootstrap(
    references: List[Dict[str, Any]],
    faces_by_path: Dict[Path, List[Face]],
    galleries: Dict[str, Dict[str, Any]],
    *,
    route: str,
    cosine_distance: Distance,
    secure_threshold: float,
    review_threshold: float,
    identity_margin: float,
    min_support: int,
    max_anchors: int,
    duplicate_threshold: float,
    candidate_limit: int,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Propone alimentadores CR3 y reevaluaciones con evidencia de grupo.

    Preview y Full RAW deben invocar esta funcion por separado. Las propuestas
    internas contienen embeddings; los diagnosticos y estadisticas nunca los
    exponen.
    """
    cr3_references = [
        reference
        for reference in references or []
        if Path(reference.get("path", "")).suffix.lower() == ".cr3"
        and _folder(reference)
        and reference.get("embedding")
    ]
    stats: Dict[str, Any] = {
        "enabled": bool(cr3_references),
        "route": route,
        "references": len(cr3_references),
        "real_faces": 0,
        "candidate_limit": int(candidate_limit),
        "proposals": 0,
        "accepted_identities": 0,
        "blocked_identities": 0,
        "feeders": 0,
        "reevaluated_faces": 0,
    }
    if not cr3_references:
        return {}, [], stats

    reference_paths = {_resolved(reference["path"]) for reference in cr3_references}
    nodes: List[Node] = []
    for raw_path, faces in (faces_by_path or {}).items():
        path = _resolved(raw_path)
        if path.suffix.lower() != ".cr3" or path in reference_paths:
            continue
        for face_index, face in enumerate(faces or []):
            if not _real_face(face):
                continue
            nodes.append(
                {
                    "path": path,
                    "face_index": int(face_index),
                    "embedding": face["embedding"],
                    "face_side": _face_side(face),
                }
            )
    stats["real_faces"] = len(nodes)

    references_by_folder = {_folder(reference): reference for reference in cr3_references}
    preliminary: Dict[str, Dict[str, Any]] = {}
    diagnostics_by_folder: Dict[str, Dict[str, Any]] = {}

    for folder, reference in references_by_folder.items():
        gallery = galleries.get(folder) or {}
        reference_path = _resolved(reference["path"])
        existing_non_root = {
            path
            for _embedding, path in _unique_gallery_entries(gallery)
            if path != reference_path
        }
        diagnostic: Dict[str, Any] = {
            "ruta": route,
            "persona": str(
                (reference.get("person") or {}).get("display_name", folder)
            ),
            "foto_raiz": str(reference_path),
            "estado": "bloqueada",
            "motivo": "sin_grupo_coherente",
            "candidatos_reales": 0,
            "grupos_coherentes": 0,
            "alimentadores": [],
            "fotos_reevaluadas": [],
        }
        diagnostics_by_folder[folder] = diagnostic

        if not gallery.get("reference_trusted", True):
            diagnostic["motivo"] = "referencia_no_confiable"
            continue
        if len(existing_non_root) >= min_support:
            diagnostic["estado"] = "no_necesaria"
            diagnostic["motivo"] = "galeria_existente_suficiente"
            continue

        root_embedding = reference["embedding"]
        root_face_side = _reference_face_side(reference)
        available: List[Node] = []
        for node in nodes:
            # Un detector puede producir embeddings faciales convincentes para
            # un maniqui, ilustracion u objeto. Durante el arranque conservador,
            # una escala facial incompatible con la referencia no puede enseñar
            # la identidad. La comparación es logarítmica y usa el límite de
            # revisión existente; si falta geometría, no inventa datos.
            if not _scale_compatible(
                node.get("face_side"), root_face_side, review_threshold
            ):
                continue
            other_owner = _other_gallery_distance(
                node, folder, galleries, cosine_distance
            )
            if other_owner is not None and other_owner <= secure_threshold:
                continue
            candidate = dict(node)
            candidate["root_distance"] = cosine_distance(
                root_embedding, node["embedding"]
            )
            available.append(candidate)
        available.sort(
            key=lambda node: (
                node["root_distance"],
                str(node["path"]).casefold(),
                node["face_index"],
            )
        )
        available = available[: max(2, int(candidate_limit))]
        diagnostic["candidatos_reales"] = len(available)

        seen: set[Tuple[Tuple[str, int], ...]] = set()
        eligible: List[Dict[str, Any]] = []
        for seed in available:
            group = _coherent_star(
                seed,
                available,
                distance=cosine_distance,
                secure_threshold=secure_threshold,
            )
            key = tuple(
                sorted(
                    (str(node["path"]).casefold(), node["face_index"])
                    for node in group
                )
            )
            if key in seen:
                continue
            seen.add(key)
            if len({node["path"] for node in group}) < min_support:
                continue
            metrics = _cluster_metrics(group, cosine_distance)
            if (
                metrics["median"] > secure_threshold
                or metrics["maximum"] > review_threshold
            ):
                continue

            root_distances = [
                cosine_distance(root_embedding, node["embedding"])
                for node in group
            ]
            root_best = min(root_distances)
            root_median = statistics.median(root_distances)
            bridge_limit = review_threshold + min(
                metrics["median"], identity_margin * 2.0
            )
            if root_best > bridge_limit:
                continue

            other_reference_medians = []
            for other_folder, other_reference in references_by_folder.items():
                if other_folder == folder:
                    continue
                other_reference_medians.append(
                    statistics.median(
                        cosine_distance(
                            other_reference["embedding"], node["embedding"]
                        )
                        for node in group
                    )
                )
            other_reference_best = (
                min(other_reference_medians) if other_reference_medians else None
            )
            reference_margin = (
                other_reference_best - root_median
                if other_reference_best is not None
                else None
            )
            if reference_margin is not None and reference_margin < identity_margin:
                continue

            negative_distances = [
                value
                for node in group
                for value in [
                    _other_gallery_distance(
                        node, folder, galleries, cosine_distance
                    )
                ]
                if value is not None
            ]
            other_gallery_best = (
                min(negative_distances) if negative_distances else None
            )
            gallery_margin = (
                other_gallery_best - metrics["median"]
                if other_gallery_best is not None
                else None
            )
            if gallery_margin is not None and gallery_margin < identity_margin:
                continue

            anchors: List[Node] = []
            for node in _rank_medoids(group, cosine_distance):
                if any(
                    cosine_distance(node["embedding"], anchor["embedding"])
                    < duplicate_threshold
                    for anchor in anchors
                ):
                    continue
                anchors.append(node)
                if len(anchors) >= max_anchors:
                    break
            if len({node["path"] for node in anchors}) < min_support:
                continue

            eligible.append(
                {
                    "nodes": anchors,
                    "root_best": root_best,
                    "root_median": root_median,
                    "internal_median": metrics["median"],
                    "internal_max": metrics["maximum"],
                    "bridge_limit": bridge_limit,
                    "reference_margin": reference_margin,
                    "gallery_margin": gallery_margin,
                }
            )

        diagnostic["grupos_coherentes"] = len(eligible)
        eligible.sort(
            key=lambda group: (
                group["root_median"],
                -len(group["nodes"]),
                group["internal_median"],
            )
        )
        if not eligible:
            continue
        if (
            len(eligible) > 1
            and eligible[1]["root_median"] - eligible[0]["root_median"]
            < identity_margin
        ):
            diagnostic["motivo"] = "grupos_competidores_sin_margen"
            continue

        winner = eligible[0]
        preliminary[folder] = {
            "reference": reference,
            "root_face_side": root_face_side,
            "anchors": winner["nodes"],
            **{key: value for key, value in winner.items() if key != "nodes"},
        }

    # Dos referencias debiles no pueden aprender el mismo grupo, ni dos grupos
    # visualmente equivalentes aunque sus fotos no coincidan por ruta.
    conflicted: set[str] = set()
    proposal_items = list(preliminary.items())
    for index, (left_folder, left) in enumerate(proposal_items):
        left_keys = {
            (node["path"], node["face_index"]) for node in left["anchors"]
        }
        for right_folder, right in proposal_items[index + 1 :]:
            right_keys = {
                (node["path"], node["face_index"])
                for node in right["anchors"]
            }
            cross_distances = [
                cosine_distance(left_node["embedding"], right_node["embedding"])
                for left_node in left["anchors"]
                for right_node in right["anchors"]
            ]
            equivalent = bool(cross_distances) and statistics.median(
                cross_distances
            ) <= secure_threshold
            if left_keys & right_keys or equivalent:
                conflicted.update({left_folder, right_folder})

    proposals = {
        folder: proposal
        for folder, proposal in preliminary.items()
        if folder not in conflicted
    }
    for folder in conflicted:
        diagnostic = diagnostics_by_folder[folder]
        diagnostic["motivo"] = "grupo_reclamado_por_varias_identidades"

    # La busqueda amplia termina aqui. Solamente los grupos ya validados forman
    # anclajes; despues se puntuan omisiones contra esos anclajes y contra todas
    # las identidades competidoras.
    decision_options: Dict[Tuple[Path, int], List[Dict[str, Any]]] = {}
    for folder, proposal in proposals.items():
        anchors = proposal["anchors"]
        anchor_keys = {
            (node["path"], node["face_index"]) for node in anchors
        }
        for node in nodes:
            if not _scale_compatible(
                node.get("face_side"),
                proposal.get("root_face_side"),
                review_threshold,
            ):
                continue
            key = (node["path"], node["face_index"])
            distances = [
                cosine_distance(node["embedding"], anchor["embedding"])
                for anchor in anchors
                if anchor["path"] != node["path"]
            ]
            if key in anchor_keys:
                if not distances:
                    continue
                score = min(distances)
                supporters = len(anchors)
                reason = "miembro_grupo_validado"
            else:
                supporters = sum(
                    value <= secure_threshold for value in distances
                )
                if supporters < min_support:
                    continue
                score = min(distances, default=999.0)
                if score > secure_threshold:
                    continue
                reason = "reevaluada_por_anclajes"

            competing = [
                value
                for other_folder, other_gallery in galleries.items()
                if other_folder != folder
                for embedding, _path in _unique_gallery_entries(other_gallery)
                for value in [cosine_distance(node["embedding"], embedding)]
            ] + [
                cosine_distance(node["embedding"], anchor["embedding"])
                for other_folder, other_proposal in proposals.items()
                if other_folder != folder
                for anchor in other_proposal["anchors"]
            ]
            other_best = min(competing) if competing else None
            if other_best is not None and other_best - score < identity_margin:
                continue
            decision_options.setdefault(key, []).append(
                {
                    "folder": folder,
                    "path": node["path"],
                    "face_index": node["face_index"],
                    "distance": score,
                    "supporter_count": supporters,
                    "identity_margin": (
                        other_best - score if other_best is not None else None
                    ),
                    "reason": reason,
                }
            )

    for options in decision_options.values():
        options.sort(key=lambda option: (option["distance"], option["folder"]))
        if (
            len(options) > 1
            and options[1]["distance"] - options[0]["distance"] < identity_margin
        ):
            continue
        proposals[options[0]["folder"]].setdefault("decisions", []).append(
            options[0]
        )

    for folder, diagnostic in diagnostics_by_folder.items():
        proposal = proposals.get(folder)
        if proposal is None:
            if diagnostic["estado"] == "bloqueada":
                stats["blocked_identities"] += 1
            continue
        diagnostic.update(
            {
                "estado": "aceptada",
                "motivo": "grupo_coherente_separado",
                "soporte_fotos": len({node["path"] for node in proposal["anchors"]}),
                "distancia_raiz_minima": round(proposal["root_best"], 6),
                "distancia_raiz_mediana": round(proposal["root_median"], 6),
                "distancia_interna_mediana": round(
                    proposal["internal_median"], 6
                ),
                "distancia_interna_maxima": round(
                    proposal["internal_max"], 6
                ),
                "limite_puente": round(proposal["bridge_limit"], 6),
                "margen_referencias": (
                    round(proposal["reference_margin"], 6)
                    if proposal["reference_margin"] is not None
                    else None
                ),
                "margen_galerias": (
                    round(proposal["gallery_margin"], 6)
                    if proposal["gallery_margin"] is not None
                    else None
                ),
                "alimentadores": [
                    str(node["path"]) for node in proposal["anchors"]
                ],
                "fotos_reevaluadas": [
                    str(decision["path"])
                    for decision in proposal.get("decisions", [])
                ],
            }
        )
        stats["accepted_identities"] += 1
        stats["feeders"] += len(proposal["anchors"])
        stats["reevaluated_faces"] += len(proposal.get("decisions", []))

    stats["proposals"] = len(preliminary)
    return proposals, list(diagnostics_by_folder.values()), stats
