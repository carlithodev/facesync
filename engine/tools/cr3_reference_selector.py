"""Selector aislado de referencia facial para archivos CR3.

El modulo trabaja con evidencia ya generada por RetinaFace y ArcFace, pero no
modifica esos modelos ni sus umbrales. Preview y Full RAW permanecen en espacios
separados; la relacion entre rutas se resuelve exclusivamente por geometria.
"""

from __future__ import annotations

import itertools
import math
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


Face = Dict[str, Any]
FaceMap = Dict[Path, List[Face]]
SizeMap = Dict[Path, Tuple[int, int]]
Distance = Callable[[Iterable[float], Iterable[float]], float]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _resolved(path: Any) -> Path:
    return Path(path).resolve(strict=False)


def _real_face(face: Face) -> bool:
    return bool(face.get("embedding")) and _safe_float(face.get("face_confidence")) > 0


def _normalized_box(face: Face, size: Tuple[int, int]) -> Optional[Tuple[float, float, float, float]]:
    width, height = size
    area = face.get("facial_area") or {}
    x = _safe_float(area.get("x"))
    y = _safe_float(area.get("y"))
    box_width = _safe_float(area.get("w"))
    box_height = _safe_float(area.get("h"))
    if width <= 0 or height <= 0 or box_width <= 0 or box_height <= 0:
        return None
    return x / width, y / height, box_width / width, box_height / height


def _transform_box(
    box: Tuple[float, float, float, float], transform: str
) -> Tuple[float, float, float, float]:
    x, y, width, height = box
    if transform.startswith("mirror_"):
        x = 1.0 - (x + width)
        transform = transform[7:]
    if transform == "identity":
        return x, y, width, height
    if transform == "rot90":
        return 1.0 - (y + height), x, height, width
    if transform == "rot180":
        return 1.0 - (x + width), 1.0 - (y + height), width, height
    if transform == "rot270":
        return y, 1.0 - (x + width), height, width
    raise ValueError(f"Transformacion geometrica desconocida: {transform}")


def _box_iou(
    left: Tuple[float, float, float, float],
    right: Tuple[float, float, float, float],
) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    x1, y1 = max(lx, rx), max(ly, ry)
    x2, y2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def _best_assignment(scores: List[List[float]]) -> List[Tuple[int, int, float]]:
    if not scores or not scores[0]:
        return []
    left_count, right_count = len(scores), len(scores[0])
    pair_count = min(left_count, right_count)
    if max(left_count, right_count) <= 7:
        best: Optional[Tuple[float, Tuple[Tuple[int, int], ...]]] = None
        if left_count <= right_count:
            for rights in itertools.permutations(range(right_count), pair_count):
                pairs = tuple((left, rights[left]) for left in range(pair_count))
                total = sum(scores[left][right] for left, right in pairs)
                candidate = (total, pairs)
                if best is None or candidate > best:
                    best = candidate
        else:
            for lefts in itertools.permutations(range(left_count), pair_count):
                pairs = tuple((lefts[right], right) for right in range(pair_count))
                total = sum(scores[left][right] for left, right in pairs)
                candidate = (total, pairs)
                if best is None or candidate > best:
                    best = candidate
        assert best is not None
        return [(left, right, scores[left][right]) for left, right in best[1]]

    candidates = sorted(
        (
            (scores[left][right], left, right)
            for left in range(left_count)
            for right in range(right_count)
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    used_left: set[int] = set()
    used_right: set[int] = set()
    result: List[Tuple[int, int, float]] = []
    for score, left, right in candidates:
        if left in used_left or right in used_right:
            continue
        used_left.add(left)
        used_right.add(right)
        result.append((left, right, score))
        if len(result) >= pair_count:
            break
    return result


def match_faces_by_geometry(
    preview_faces: List[Face],
    preview_size: Tuple[int, int],
    fullraw_faces: List[Face],
    fullraw_size: Tuple[int, int],
    *,
    min_iou: float,
    min_margin: float,
) -> Dict[str, Any]:
    """Relaciona caras preview/Full RAW sin comparar sus embeddings."""
    preview_boxes = [_normalized_box(face, preview_size) for face in preview_faces]
    fullraw_boxes = [_normalized_box(face, fullraw_size) for face in fullraw_faces]
    transforms = (
        "identity",
        "rot90",
        "rot180",
        "rot270",
        "mirror_identity",
        "mirror_rot90",
        "mirror_rot180",
        "mirror_rot270",
    )
    best_transform = "identity"
    best_pairs: List[Tuple[int, int, float]] = []
    best_total = -1.0
    best_scores: List[List[float]] = []
    for transform in transforms:
        scores: List[List[float]] = []
        for preview_box in preview_boxes:
            row = []
            for fullraw_box in fullraw_boxes:
                if preview_box is None or fullraw_box is None:
                    row.append(0.0)
                else:
                    row.append(_box_iou(preview_box, _transform_box(fullraw_box, transform)))
            scores.append(row)
        pairs = _best_assignment(scores)
        total = sum(score for _left, _right, score in pairs)
        candidate_key = (total, -transforms.index(transform))
        best_key = (best_total, -transforms.index(best_transform))
        if candidate_key > best_key:
            best_transform = transform
            best_pairs = pairs
            best_total = total
            best_scores = scores

    one_to_one = len(preview_faces) == len(fullraw_faces) == 1
    public_pairs = []
    for preview_index, fullraw_index, iou in sorted(best_pairs):
        alternatives = [
            best_scores[preview_index][index]
            for index in range(len(fullraw_faces))
            if index != fullraw_index
        ] + [
            best_scores[index][fullraw_index]
            for index in range(len(preview_faces))
            if index != preview_index
        ]
        margin = iou - max(alternatives, default=0.0)
        real_pair = (
            _real_face(preview_faces[preview_index])
            and _real_face(fullraw_faces[fullraw_index])
        )
        accepted = real_pair and (
            one_to_one or (iou >= min_iou and margin >= min_margin)
        )
        public_pairs.append({
            "preview_index": preview_index,
            "fullraw_index": fullraw_index,
            "iou": iou,
            "margin": margin,
            "accepted": accepted,
            "reason": (
                "single_face_unambiguous"
                if accepted and one_to_one
                else "geometry_supported"
                if accepted
                else "fallback_face"
                if not real_pair
                else "ambiguous_geometry"
            ),
        })
    return {
        "transform": best_transform,
        "total_iou": max(0.0, best_total),
        "pairs": public_pairs,
    }


def _face_quality(face: Face, size: Tuple[int, int], min_side_pixels: float) -> Dict[str, float]:
    area = face.get("facial_area") or {}
    width = max(0.0, _safe_float(area.get("w")))
    height = max(0.0, _safe_float(area.get("h")))
    image_width, image_height = size
    min_side = min(width, height)
    area_ratio = (
        (width * height) / (image_width * image_height)
        if image_width > 0 and image_height > 0 else 0.0
    )
    confidence = max(0.0, min(1.0, _safe_float(face.get("face_confidence"))))
    resolution = min(1.0, min_side / max(1.0, min_side_pixels))
    return {
        "confidence": confidence,
        "min_side_pixels": min_side,
        "area_ratio": area_ratio,
        "score": (0.65 * confidence) + (0.25 * resolution) + (0.10 * min(1.0, area_ratio * 25.0)),
    }


def _cluster_stats(cluster: List[Dict[str, Any]], distance: Distance) -> Dict[str, Any]:
    pair_distances = []
    for left in range(len(cluster)):
        for right in range(left + 1, len(cluster)):
            if cluster[left]["path"] == cluster[right]["path"]:
                continue
            pair_distances.append(distance(
                cluster[left]["face"]["embedding"],
                cluster[right]["face"]["embedding"],
            ))
    return {
        "support_count": len({node["path"] for node in cluster}),
        "median_pair_distance": (
            statistics.median(pair_distances) if pair_distances else 999.0
        ),
    }


def _coherent_star_group(
    seed: Dict[str, Any],
    nodes: List[Dict[str, Any]],
    distance: Distance,
    max_distance: float,
) -> List[Dict[str, Any]]:
    """Forma un nucleo sin expansion transitiva y con una cara por foto."""
    seed_embedding = seed["face"]["embedding"]
    best_by_path: Dict[Path, Tuple[float, Dict[str, Any]]] = {}
    for node in nodes:
        node_distance = distance(seed_embedding, node["face"]["embedding"])
        if node_distance > max_distance:
            continue
        previous = best_by_path.get(node["path"])
        if previous is None or (node_distance, node["face_index"]) < (
            previous[0], previous[1]["face_index"]
        ):
            best_by_path[node["path"]] = (node_distance, node)
    group = [item[1] for item in best_by_path.values()]
    if len(group) < 2:
        return group

    # Recentrar una vez elimina miembros unidos solamente por el primer soporte.
    medoid = _rank_medoid_nodes(group, distance)[0]
    medoid_embedding = medoid["face"]["embedding"]
    return [
        node for node in group
        if distance(medoid_embedding, node["face"]["embedding"]) <= max_distance
    ]


def _rank_medoid_nodes(
    cluster: List[Dict[str, Any]], distance: Distance
) -> List[Dict[str, Any]]:
    ranked = []
    for node in cluster:
        peers = [other for other in cluster if other["path"] != node["path"]]
        average = (
            statistics.fmean(
                distance(node["face"]["embedding"], other["face"]["embedding"])
                for other in peers
            )
            if peers else 999.0
        )
        ranked.append((average, -node["quality"]["score"], str(node["path"]).casefold(), node))
    return [item[-1] for item in sorted(ranked, key=lambda item: item[:-1])]


def _accepted_pair_for_index(
    geometry: Dict[str, Any], route: str, index: int
) -> Optional[Dict[str, Any]]:
    key = "preview_index" if route == "preview" else "fullraw_index"
    for pair in geometry.get("pairs") or []:
        if pair.get("accepted") and int(pair.get(key, -1)) == index:
            return pair
    return None


def select_cr3_reference_evidence(
    references: List[Dict[str, Any]],
    preview_faces_by_path: FaceMap,
    fullraw_faces_by_path: FaceMap,
    preview_sizes_by_path: SizeMap,
    fullraw_sizes_by_path: SizeMap,
    *,
    cosine_distance: Distance,
    recurrence_threshold: float,
    peer_distance: float,
    identity_margin: float,
    geometry_min_iou: float,
    geometry_min_margin: float,
    min_support: int,
    min_face_side_pixels: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Selecciona una sola ancla operativa por referencia CR3.

    El resultado conserva la referencia raiz y devuelve caras distintas para
    preview y Full RAW. Los diagnósticos nunca contienen embeddings.
    """
    if not references:
        return [], []
    reference_paths = {_resolved(ref["path"]) for ref in references}
    preview_faces = {_resolved(path): list(faces) for path, faces in preview_faces_by_path.items()}
    fullraw_faces = {_resolved(path): list(faces) for path, faces in fullraw_faces_by_path.items()}
    preview_sizes = {_resolved(path): size for path, size in preview_sizes_by_path.items()}
    fullraw_sizes = {_resolved(path): size for path, size in fullraw_sizes_by_path.items()}

    route_data = {
        "preview": (preview_faces, preview_sizes),
        "fullraw": (fullraw_faces, fullraw_sizes),
    }
    nodes_by_route: Dict[str, List[Dict[str, Any]]] = {"preview": [], "fullraw": []}
    for route, (faces_by_path, sizes_by_path) in route_data.items():
        for path, faces in faces_by_path.items():
            if path in reference_paths:
                continue
            size = sizes_by_path.get(path, (0, 0))
            for face_index, face in enumerate(faces):
                if not _real_face(face):
                    continue
                nodes_by_route[route].append({
                    "path": path,
                    "face_index": face_index,
                    "face": face,
                    "quality": _face_quality(face, size, min_face_side_pixels),
                })

    root_pairs: Dict[int, Dict[str, Any]] = {}
    root_faces_by_route: Dict[str, List[Dict[str, Any]]] = {"preview": [], "fullraw": []}
    for ref_index, ref in enumerate(references):
        path = _resolved(ref["path"])
        preview = preview_faces.get(path) or list(ref.get("candidate_faces") or [])
        fullraw = fullraw_faces.get(path) or []
        geometry = match_faces_by_geometry(
            preview,
            preview_sizes.get(path, (0, 0)),
            fullraw,
            fullraw_sizes.get(path, (0, 0)),
            min_iou=geometry_min_iou,
            min_margin=geometry_min_margin,
        )
        accepted = [pair for pair in geometry["pairs"] if pair["accepted"]]
        root_pairs[ref_index] = {
            "path": path,
            "preview_faces": preview,
            "fullraw_faces": fullraw,
            "geometry": geometry,
            "accepted": accepted,
        }
        for pair_index, pair in enumerate(accepted):
            person = ref.get("person") or {}
            person_key = str(
                person.get("folder_name")
                or person.get("display_name")
                or ref_index
            ).casefold()
            root_faces_by_route["preview"].append({
                "ref_index": ref_index,
                "pair_index": pair_index,
                "person_key": person_key,
                "face": preview[pair["preview_index"]],
                "quality": _face_quality(
                    preview[pair["preview_index"]],
                    preview_sizes.get(path, (0, 0)),
                    min_face_side_pixels,
                ),
            })
            root_faces_by_route["fullraw"].append({
                "ref_index": ref_index,
                "pair_index": pair_index,
                "person_key": person_key,
                "face": fullraw[pair["fullraw_index"]],
                "quality": _face_quality(
                    fullraw[pair["fullraw_index"]],
                    fullraw_sizes.get(path, (0, 0)),
                    min_face_side_pixels,
                ),
            })

    candidates: Dict[Tuple[int, int, str], List[Dict[str, Any]]] = {}
    weak_search_audits: Dict[Tuple[int, int, str], Dict[str, Any]] = {}
    for route in ("preview", "fullraw"):
        route_roots = root_faces_by_route[route]
        for root in route_roots:
            root_embedding = root["face"]["embedding"]
            route_nodes = nodes_by_route[route]
            direct_nodes = [
                node for node in route_nodes
                if cosine_distance(
                    root_embedding, node["face"]["embedding"]
                ) <= recurrence_threshold
            ]
            selection_mode = "direct_recurrence"
            seed_nodes = direct_nodes
            if not seed_nodes:
                # Búsqueda para seleccionar referencia, no para entregar fotos:
                # sólo examina los candidatos visualmente más cercanos y exige
                # un grupo coherente claramente separado del segundo grupo.
                selection_mode = "separated_nearest_group"
                seed_nodes = sorted(
                    route_nodes,
                    key=lambda node: (
                        cosine_distance(
                            root_embedding, node["face"]["embedding"]
                        ),
                        str(node["path"]).casefold(),
                        node["face_index"],
                    ),
                )[: max(min_support * 2, 2)]
            seen_groups: set[Tuple[Tuple[str, int], ...]] = set()
            root_candidates: List[Dict[str, Any]] = []
            for seed in seed_nodes:
                cluster = _coherent_star_group(
                    seed, route_nodes, cosine_distance, peer_distance
                )
                group_key = tuple(sorted(
                    (str(node["path"]).casefold(), int(node["face_index"]))
                    for node in cluster
                ))
                if group_key in seen_groups:
                    continue
                seen_groups.add(group_key)
                stats = _cluster_stats(cluster, cosine_distance)
                if stats["support_count"] < min_support:
                    continue
                root_distances = [
                    cosine_distance(root_embedding, node["face"]["embedding"])
                    for node in cluster
                ]
                direct_support = sum(
                    distance <= recurrence_threshold for distance in root_distances
                )
                if selection_mode == "direct_recurrence" and direct_support < 1:
                    continue
                if (
                    selection_mode == "separated_nearest_group"
                    and stats["median_pair_distance"] > recurrence_threshold
                ):
                    continue
                own_best = min(root_distances)
                own_median = statistics.median(root_distances)
                other_distances = [
                    cosine_distance(
                        other["face"]["embedding"], node["face"]["embedding"]
                    )
                    for other in route_roots
                    if other["person_key"] != root["person_key"]
                    for node in cluster
                ]
                other_best = min(other_distances) if other_distances else None
                separation = (
                    other_best - own_best if other_best is not None else None
                )
                if separation is not None and separation < identity_margin:
                    continue
                medoids = _rank_medoid_nodes(cluster, cosine_distance)
                candidate = {
                    "route": route,
                    "ref_index": root["ref_index"],
                    "pair_index": root["pair_index"],
                    "cluster": cluster,
                    "medoids": medoids,
                    "support_count": stats["support_count"],
                    "direct_support_count": direct_support,
                    "median_pair_distance": stats["median_pair_distance"],
                    "root_best_distance": own_best,
                    "root_median_distance": own_median,
                    "other_best_distance": other_best,
                    "separation_margin": separation,
                    "root_quality": root["quality"]["score"],
                    "selection_mode": selection_mode,
                }
                root_candidates.append(candidate)

            if selection_mode == "separated_nearest_group":
                root_candidates.sort(key=lambda item: (
                    item["root_median_distance"],
                    item["median_pair_distance"],
                    -item["support_count"],
                ))
                audit = {
                    "grupos_coherentes": len(root_candidates),
                    "distancia_mejor_grupo": (
                        root_candidates[0]["root_median_distance"]
                        if root_candidates else None
                    ),
                    "distancia_segundo_grupo": (
                        root_candidates[1]["root_median_distance"]
                        if len(root_candidates) > 1 else None
                    ),
                    "margen_requerido": identity_margin,
                    "margen_obtenido": None,
                    "aceptada": False,
                }
                if len(root_candidates) < 2:
                    root_candidates = []
                else:
                    group_margin = (
                        root_candidates[1]["root_median_distance"]
                        - root_candidates[0]["root_median_distance"]
                    )
                    audit["margen_obtenido"] = group_margin
                    if group_margin < identity_margin:
                        root_candidates = []
                    else:
                        root_candidates[0]["nearest_group_margin"] = group_margin
                        root_candidates = root_candidates[:1]
                        audit["aceptada"] = True
                weak_search_audits[(
                    root["ref_index"], root["pair_index"], route
                )] = audit
            candidates.setdefault(
                (root["ref_index"], root["pair_index"], route), []
            ).extend(root_candidates)

    selections: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for ref_index, ref in enumerate(references):
        root = root_pairs[ref_index]
        eligible = [
            candidate
            for (candidate_ref, _pair, _route), route_candidates in candidates.items()
            if candidate_ref == ref_index
            for candidate in route_candidates
        ]
        eligible.sort(key=lambda item: (
            0 if item["selection_mode"] == "direct_recurrence" else 1,
            -item["support_count"],
            -item["direct_support_count"],
            item["median_pair_distance"],
            -(item["separation_margin"] if item["separation_margin"] is not None else 999.0),
            -item["root_quality"],
            item["root_best_distance"],
            0 if item["route"] == "preview" else 1,
        ))

        chosen = None
        chosen_pair = None
        chosen_geometry = None
        chosen_preview_face = None
        chosen_fullraw_face = None
        chosen_node = None
        for candidate in eligible:
            route = candidate["route"]
            for node in candidate["medoids"]:
                path = node["path"]
                geometry = match_faces_by_geometry(
                    preview_faces.get(path, []),
                    preview_sizes.get(path, (0, 0)),
                    fullraw_faces.get(path, []),
                    fullraw_sizes.get(path, (0, 0)),
                    min_iou=geometry_min_iou,
                    min_margin=geometry_min_margin,
                )
                pair = _accepted_pair_for_index(geometry, route, node["face_index"])
                if pair is None:
                    continue
                chosen = candidate
                chosen_pair = pair
                chosen_geometry = geometry
                chosen_node = node
                chosen_preview_face = preview_faces[path][pair["preview_index"]]
                chosen_fullraw_face = fullraw_faces[path][pair["fullraw_index"]]
                break
            if chosen is not None:
                break

        root_pair = None
        if root["accepted"]:
            root_pair = max(
                root["accepted"],
                key=lambda pair: (pair["iou"], pair["margin"], -pair["preview_index"]),
            )
        if chosen is None and root_pair is not None:
            chosen_preview_face = root["preview_faces"][root_pair["preview_index"]]
            chosen_fullraw_face = root["fullraw_faces"][root_pair["fullraw_index"]]

        promoted = chosen is not None and chosen_node is not None
        anchor_path = chosen_node["path"] if promoted else root["path"]
        selected_route = chosen["route"] if promoted else "root"
        selection = {
            "reference": ref,
            "root_path": root["path"],
            "anchor_path": anchor_path,
            "preview_face": chosen_preview_face,
            "fullraw_face": chosen_fullraw_face,
            "selected_route": selected_route,
            "promoted": promoted,
        }
        selections.append(selection)

        preview_quality = (
            _face_quality(
                chosen_preview_face,
                preview_sizes.get(anchor_path, (0, 0)),
                min_face_side_pixels,
            ) if chosen_preview_face else None
        )
        fullraw_quality = (
            _face_quality(
                chosen_fullraw_face,
                fullraw_sizes.get(anchor_path, (0, 0)),
                min_face_side_pixels,
            ) if chosen_fullraw_face else None
        )
        root_preview_quality = (
            _face_quality(
                root["preview_faces"][root_pair["preview_index"]],
                preview_sizes.get(root["path"], (0, 0)),
                min_face_side_pixels,
            ) if root_pair else None
        )
        root_fullraw_quality = (
            _face_quality(
                root["fullraw_faces"][root_pair["fullraw_index"]],
                fullraw_sizes.get(root["path"], (0, 0)),
                min_face_side_pixels,
            ) if root_pair else None
        )
        person = ref.get("person") or {}
        diagnostic = {
            "persona": str(person.get("display_name", "")),
            "referencia_excel": str(person.get("reference_value", ref.get("reference_value", ""))),
            "foto_raiz": str(root["path"]),
            "codigo_raiz_conservado": True,
            "estado": "ancla_operativa_promovida" if promoted else "referencia_raiz_conservada",
            "ruta_seleccionada": selected_route,
            "foto_ancla": str(anchor_path),
            "soporte_fotos": int(chosen["support_count"]) if promoted else 0,
            "soporte_directo": int(chosen["direct_support_count"]) if promoted else 0,
            "distancia_raiz_minima": round(float(chosen["root_best_distance"]), 6) if promoted else None,
            "distancia_raiz_mediana": round(float(chosen["root_median_distance"]), 6) if promoted else None,
            "distancia_mediana_grupo": round(float(chosen["median_pair_distance"]), 6) if promoted else None,
            "margen_otras_identidades": (
                round(float(chosen["separation_margin"]), 6)
                if promoted and chosen["separation_margin"] is not None else None
            ),
            "margen_segundo_grupo": (
                round(float(chosen["nearest_group_margin"]), 6)
                if promoted and chosen.get("nearest_group_margin") is not None
                else None
            ),
            "preview": {
                "confianza": round(preview_quality["confidence"], 6),
                "lado_minimo_px": round(preview_quality["min_side_pixels"], 2),
                "proporcion_area": round(preview_quality["area_ratio"], 6),
            } if preview_quality else None,
            "fullraw": {
                "confianza": round(fullraw_quality["confidence"], 6),
                "lado_minimo_px": round(fullraw_quality["min_side_pixels"], 2),
                "proporcion_area": round(fullraw_quality["area_ratio"], 6),
            } if fullraw_quality else None,
            "raiz_preview": {
                "confianza": round(root_preview_quality["confidence"], 6),
                "lado_minimo_px": round(root_preview_quality["min_side_pixels"], 2),
                "proporcion_area": round(root_preview_quality["area_ratio"], 6),
            } if root_preview_quality else None,
            "raiz_fullraw": {
                "confianza": round(root_fullraw_quality["confidence"], 6),
                "lado_minimo_px": round(root_fullraw_quality["min_side_pixels"], 2),
                "proporcion_area": round(root_fullraw_quality["area_ratio"], 6),
            } if root_fullraw_quality else None,
            "geometria": {
                "transformacion": (
                    chosen_geometry["transform"] if promoted and chosen_geometry else root["geometry"]["transform"]
                ),
                "iou": round(float(chosen_pair["iou"]), 6) if promoted and chosen_pair else (
                    round(float(root_pair["iou"]), 6) if root_pair else None
                ),
                "margen": round(float(chosen_pair["margin"]), 6) if promoted and chosen_pair else (
                    round(float(root_pair["margin"]), 6) if root_pair else None
                ),
                "ambigua": not bool(chosen_pair if promoted else root_pair),
            },
            "busqueda_grupo_cercano": [
                {
                    "ruta": route,
                    "rostro_raiz": pair_index + 1,
                    "grupos_coherentes": int(audit["grupos_coherentes"]),
                    "distancia_mejor_grupo": (
                        round(float(audit["distancia_mejor_grupo"]), 6)
                        if audit["distancia_mejor_grupo"] is not None else None
                    ),
                    "distancia_segundo_grupo": (
                        round(float(audit["distancia_segundo_grupo"]), 6)
                        if audit["distancia_segundo_grupo"] is not None else None
                    ),
                    "margen_obtenido": (
                        round(float(audit["margen_obtenido"]), 6)
                        if audit["margen_obtenido"] is not None else None
                    ),
                    "margen_requerido": round(float(audit["margen_requerido"]), 6),
                    "aceptada": bool(audit["aceptada"]),
                }
                for (audit_ref, pair_index, route), audit in sorted(
                    weak_search_audits.items(), key=lambda item: item[0]
                )
                if audit_ref == ref_index
            ],
            "motivo": (
                "grupo_coherente_conectado_a_la_referencia"
                if promoted and chosen["selection_mode"] == "direct_recurrence"
                else "grupo_mas_cercano_coherente_y_separado"
                if promoted
                else "sin_soporte_coherente_y_separado"
                if root_pair is not None
                else "sin_correspondencia_geometrica_segura"
            ),
        }
        diagnostics.append(diagnostic)

    return selections, diagnostics
