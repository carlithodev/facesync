"""Medición CR3 para evaluación; nunca participa en la clasificación.

El módulo conserva los embeddings únicamente en memoria. Los artefactos de
salida contienen cajas, confianza y distancias, pero no vectores biométricos.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def load_manifest(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Manifiesto CR3 inválido o con versión no soportada.")
    identities = data.get("identities")
    photos = data.get("photos")
    if not isinstance(identities, list) or not isinstance(photos, list):
        raise ValueError("El manifiesto requiere identities y photos.")
    identity_ids = [str(item.get("id") or "") for item in identities]
    if not all(identity_ids) or len(identity_ids) != len(set(identity_ids)):
        raise ValueError("Las identidades deben tener ids únicos y no vacíos.")
    files = [str(item.get("file") or "") for item in photos]
    if not all(files) or len(files) != len(set(name.casefold() for name in files)):
        raise ValueError("Las fotografías deben tener nombres únicos y no vacíos.")
    known = set(identity_ids)
    for item in photos:
        targets = item.get("target_identities")
        companions = item.get("companion_identities")
        if not isinstance(targets, list) or not isinstance(companions, list):
            raise ValueError(f"Etiquetas incompletas en {item.get('file')}.")
        unknown = (set(targets) | set(companions)) - known
        if unknown:
            raise ValueError(f"Identidades desconocidas en {item.get('file')}: {sorted(unknown)}")
        no_target = bool(item.get("no_target"))
        if no_target == bool(targets):
            raise ValueError(f"no_target contradice target_identities en {item.get('file')}.")
    return data


def verify_manifest_files(manifest: Dict[str, Any], source_root: Path) -> List[Dict[str, Any]]:
    verified: List[Dict[str, Any]] = []
    for item in manifest["photos"]:
        path = source_root / item["file"]
        if not path.is_file():
            raise FileNotFoundError(f"Falta la fotografía etiquetada: {path}")
        size = path.stat().st_size
        if size != int(item["size_bytes"]):
            raise ValueError(f"Tamaño distinto para {item['file']}: {size}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if digest != str(item["sha256"]).upper():
            raise ValueError(f"SHA-256 distinto para {item['file']}")
        verified.append({**item, "path": path})
    extras = sorted(
        path.name
        for path in source_root.iterdir()
        if path.is_file() and path.suffix.lower() == ".cr3"
        and path.name.casefold() not in {item["file"].casefold() for item in manifest["photos"]}
    )
    if extras:
        raise ValueError(f"Hay CR3 sin etiquetar en el origen: {extras}")
    return verified


def _distance(motor: Any, left: List[float], right: List[float]) -> float:
    return float(motor._cosine_distance(left, right))


def _round(value: Any, digits: int = 6) -> Any:
    if value is None:
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _primary_face(faces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not faces:
        return None
    return max(
        faces,
        key=lambda face: (
            float((face.get("facial_area") or {}).get("w", 0))
            * float((face.get("facial_area") or {}).get("h", 0)),
            float(face.get("face_confidence", 0)),
        ),
    )


def _face_public(face: Dict[str, Any], image_size: tuple[int, int], index: int) -> Dict[str, Any]:
    width, height = image_size
    area = dict(face.get("facial_area") or {})
    x = float(area.get("x", 0))
    y = float(area.get("y", 0))
    w = float(area.get("w", 0))
    h = float(area.get("h", 0))
    left_eye = area.get("left_eye")
    right_eye = area.get("right_eye")

    def point(value: Any) -> Optional[tuple[float, float]]:
        if isinstance(value, dict):
            try:
                return float(value["x"]), float(value["y"])
            except (KeyError, TypeError, ValueError):
                return None
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                return None
        return None

    left_point = point(left_eye)
    right_point = point(right_eye)
    eye_line_angle = None
    inter_eye_ratio = None
    if left_point and right_point:
        delta_x = right_point[0] - left_point[0]
        delta_y = right_point[1] - left_point[1]
        eye_line_angle = math.degrees(math.atan2(delta_y, delta_x))
        inter_eye_ratio = math.hypot(delta_x, delta_y) / w if w else None
    return {
        "face_index": index,
        "confidence": _round(face.get("face_confidence", 0)),
        "facial_area": {"x": _round(x, 2), "y": _round(y, 2), "w": _round(w, 2), "h": _round(h, 2)},
        "normalized_area": {
            "x": _round(x / width if width else 0),
            "y": _round(y / height if height else 0),
            "w": _round(w / width if width else 0),
            "h": _round(h / height if height else 0),
        },
        "min_side_pixels": _round(min(w, h), 2),
        "image_area_ratio": _round((w * h) / (width * height) if width and height else 0),
        "eye_line_angle_degrees": _round(eye_line_angle, 3),
        "inter_eye_to_face_width": _round(inter_eye_ratio),
    }


def _route_image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def _image_quality(path: Path) -> Dict[str, Any]:
    """Calcula iluminación de diagnóstico sobre una miniatura, sin alterar el RAW."""
    from PIL import Image, ImageStat

    with Image.open(path) as image:
        gray = image.convert("L")
        gray.thumbnail((256, 256))
        stats = ImageStat.Stat(gray)
        histogram = gray.histogram()
        pixels = max(1, sum(histogram))
        return {
            "mean_luminance": _round(stats.mean[0], 3),
            "luminance_stddev": _round(stats.stddev[0], 3),
            "shadow_clip_ratio": _round(sum(histogram[:6]) / pixels),
            "highlight_clip_ratio": _round(sum(histogram[250:]) / pixels),
        }


def _percentile(sorted_values: List[float], percentile: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _distribution(values: Iterable[Any]) -> Dict[str, Any]:
    clean = sorted(
        float(value) for value in values
        if value is not None and math.isfinite(float(value))
    )
    if not clean:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
            "stddev": None,
        }
    return {
        "count": len(clean),
        "min": _round(clean[0]),
        "p10": _round(_percentile(clean, 0.10)),
        "p25": _round(_percentile(clean, 0.25)),
        "median": _round(_percentile(clean, 0.50)),
        "p75": _round(_percentile(clean, 0.75)),
        "p90": _round(_percentile(clean, 0.90)),
        "max": _round(clean[-1]),
        "mean": _round(statistics.fmean(clean)),
        "stddev": _round(statistics.pstdev(clean)),
    }


def _pearson(left: List[float], right: List[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    delta_left = [value - mean_left for value in left]
    delta_right = [value - mean_right for value in right]
    denominator = math.sqrt(
        sum(value * value for value in delta_left)
        * sum(value * value for value in delta_right)
    )
    if denominator == 0:
        return None
    return _round(
        sum(a * b for a, b in zip(delta_left, delta_right)) / denominator
    )


def _angle_gap(left: Any, right: Any) -> Optional[float]:
    if left is None or right is None:
        return None
    difference = abs(float(left) - float(right)) % 360.0
    return min(difference, 360.0 - difference)


def _metric_counts(rows: Iterable[Dict[str, Any]], identities: Iterable[str]) -> Dict[str, Any]:
    identity_list = list(identities)
    counts = {identity: {"tp": 0, "fp": 0, "fn": 0} for identity in identity_list}
    exact_errors: List[Dict[str, Any]] = []
    total_target = total_predicted = total_correct = 0
    for row in rows:
        expected = set(row.get("target_identities") or [])
        predicted = row.get("predicted_identity")
        total_target += len(expected)
        total_predicted += int(bool(predicted))
        if predicted and predicted in expected:
            total_correct += 1
        for identity in identity_list:
            if identity in expected and predicted == identity:
                counts[identity]["tp"] += 1
            elif identity in expected:
                counts[identity]["fn"] += 1
            elif predicted == identity:
                counts[identity]["fp"] += 1
        if (predicted or expected) and predicted not in expected:
            exact_errors.append({
                "file": row["file"],
                "expected": sorted(expected),
                "predicted": predicted,
                "error": "false_positive" if predicted else "false_negative",
            })
    by_identity: Dict[str, Any] = {}
    for identity, value in counts.items():
        tp, fp, fn = value["tp"], value["fp"], value["fn"]
        by_identity[identity] = {
            **value,
            "precision": _round(tp / (tp + fp) if tp + fp else None),
            "recall": _round(tp / (tp + fn) if tp + fn else None),
        }
    return {
        "by_identity": by_identity,
        "overall": {
            "target_photos": total_target,
            "predicted_photos": total_predicted,
            "correct_photos": total_correct,
            "precision": _round(total_correct / total_predicted if total_predicted else None),
            "recall": _round(total_correct / total_target if total_target else None),
        },
        "errors": exact_errors,
    }


def _scene_pose(scene: str) -> str:
    value = str(scene or "").casefold()
    if "perfil" in value:
        return "perfil"
    if "cuerpo_completo" in value:
        return "cuerpo_completo"
    if "retrato" in value:
        return "retrato"
    return "sin_etiqueta"


def _scene_illumination(scene: str) -> str:
    value = str(scene or "").casefold()
    if "sobreexpuesto" in value:
        return "sobreexpuesto"
    if "subexpuesto" in value:
        return "subexpuesto"
    return "normal"


def _orientation(image_size: Dict[str, Any]) -> str:
    width = float(image_size.get("width") or 0)
    height = float(image_size.get("height") or 0)
    if width <= 0 or height <= 0:
        return "desconocida"
    ratio = width / height
    if ratio > 1.02:
        return "horizontal"
    if ratio < 0.98:
        return "vertical"
    return "cuadrada"


def _normalized_iou(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    try:
        lx, ly = float(left["x"]), float(left["y"])
        lw, lh = float(left["w"]), float(left["h"])
        rx, ry = float(right["x"]), float(right["y"])
        rw, rh = float(right["w"]), float(right["h"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if min(lw, lh, rw, rh) <= 0:
        return 0.0
    x1, y1 = max(lx, rx), max(ly, ry)
    x2, y2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def _pair_class(left: Dict[str, Any], right: Dict[str, Any], *, cross: bool = False) -> str:
    if cross and left["file"].casefold() == right["file"].casefold():
        return "corresponding_file"
    left_identity = left.get("identity")
    right_identity = right.get("identity")
    if left_identity and right_identity:
        return "same_identity" if left_identity == right_identity else "different_identity"
    return "no_target_control"


def _auc_lower_is_match(true_values: List[float], false_values: List[float]) -> Optional[float]:
    if not true_values or not false_values:
        return None
    wins = 0.0
    for true_value in true_values:
        for false_value in false_values:
            if true_value < false_value:
                wins += 1.0
            elif true_value == false_value:
                wins += 0.5
    return _round(wins / (len(true_values) * len(false_values)))


def _comparison_summary(pairs: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    def calculate(selected: List[Dict[str, Any]]) -> Dict[str, Any]:
        grouped: Dict[str, List[float]] = defaultdict(list)
        for pair in selected:
            grouped[pair["pair_class"]].append(float(pair["distance"]))
        true_values = grouped.get("same_identity", [])
        false_values = grouped.get("different_identity", [])
        return {
            "distributions": {
                name: _distribution(grouped.get(name, []))
                for name in ("same_identity", "different_identity", "no_target_control")
            },
            "human_identity_separation": {
                "auc_lower_is_match": _auc_lower_is_match(true_values, false_values),
                "true_accept_rate_at_current_threshold": _round(
                    sum(value <= threshold for value in true_values) / len(true_values)
                ) if true_values else None,
                "false_accept_rate_at_current_threshold": _round(
                    sum(value <= threshold for value in false_values) / len(false_values)
                ) if false_values else None,
                "minimum_different_identity_distance": _round(min(false_values)) if false_values else None,
                "p90_true_to_min_false_margin": _round(
                    min(false_values) - float(_percentile(sorted(true_values), 0.90))
                ) if true_values and false_values else None,
                "diagnostic_threshold_only": threshold,
            },
        }

    result = calculate(pairs)
    detected_only = [pair for pair in pairs if pair.get("both_detected_faces", False)]
    result["detected_faces_only"] = calculate(detected_only)
    result["pairs_involving_fallback"] = len(pairs) - len(detected_only)
    return result


def _condition_sensitivity(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    true_pairs = [
        pair for pair in pairs
        if pair["pair_class"] == "same_identity" and pair.get("both_detected_faces", False)
    ]
    distances = [float(pair["distance"]) for pair in true_pairs]
    luminance_gaps = [float(pair["luminance_gap"]) for pair in true_pairs]
    size_gaps = [float(pair["face_area_log_gap"]) for pair in true_pairs]
    eye_angle_pairs = [
        pair for pair in true_pairs if pair.get("eye_angle_gap_degrees") is not None
    ]
    size_values = sorted(size_gaps)
    low_size = _percentile(size_values, 0.25)
    high_size = _percentile(size_values, 0.75)
    return {
        "sample_count": len(true_pairs),
        "correlations": {
            "distance_vs_luminance_gap": _pearson(luminance_gaps, distances),
            "distance_vs_face_area_log_gap": _pearson(size_gaps, distances),
            "distance_vs_eye_angle_gap": _pearson(
                [float(pair["eye_angle_gap_degrees"]) for pair in eye_angle_pairs],
                [float(pair["distance"]) for pair in eye_angle_pairs],
            ),
        },
        "pose": {
            "same_tag": _distribution(
                pair["distance"] for pair in true_pairs if not pair["pose_changed"]
            ),
            "different_tag": _distribution(
                pair["distance"] for pair in true_pairs if pair["pose_changed"]
            ),
        },
        "illumination": {
            "both_normal": _distribution(
                pair["distance"] for pair in true_pairs if not pair["involves_extreme_exposure"]
            ),
            "involves_annotated_extreme": _distribution(
                pair["distance"] for pair in true_pairs if pair["involves_extreme_exposure"]
            ),
        },
        "face_size_gap": {
            "p25_boundary": _round(low_size),
            "p75_boundary": _round(high_size),
            "low_gap": _distribution(
                pair["distance"] for pair in true_pairs
                if low_size is not None and pair["face_area_log_gap"] <= low_size
            ),
            "high_gap": _distribution(
                pair["distance"] for pair in true_pairs
                if high_size is not None and pair["face_area_log_gap"] >= high_size
            ),
        },
    }


def _public_sample(sample: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value for key, value in sample.items()
        if not key.startswith("_")
    }


def _build_representation_analysis(
    motor: Any,
    verified: List[Dict[str, Any]],
    internal: Dict[str, Dict[str, Dict[str, Any]]],
    selected_truth_faces: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]],
    public_photos: List[Dict[str, Any]],
    threshold: float,
) -> Dict[str, Any]:
    """Compara rutas exclusivamente como diagnóstico; no toma decisiones productivas."""
    routes = ("preview", "fullraw")
    public_by_file = {photo["file"]: photo for photo in public_photos}
    samples: Dict[str, List[Dict[str, Any]]] = {route: [] for route in routes}

    for route in routes:
        for item in verified:
            faces = internal[route][item["file"]].get("faces") or []
            selected: List[tuple[Optional[str], Dict[str, Any]]] = []
            for identity in item["target_identities"]:
                face = selected_truth_faces[route][identity].get(item["file"])
                if face:
                    selected.append((identity, face))
            if not item["target_identities"]:
                face = _primary_face(faces)
                if face:
                    selected.append((None, face))
            for identity, face in selected:
                face_index = next(
                    (index for index, candidate in enumerate(faces) if candidate is face),
                    0,
                )
                route_public = public_by_file[item["file"]]["routes"][route]
                public_face = route_public["faces"][face_index]
                samples[route].append({
                    "file": item["file"],
                    "identity": identity,
                    "face_index": face_index,
                    "no_target": bool(item["no_target"]),
                    "scene": item.get("scene") or "sin_etiqueta",
                    "sequence": item.get("sequence") or "sin_secuencia",
                    "pose_tag": _scene_pose(item.get("scene") or ""),
                    "illumination_tag": _scene_illumination(item.get("scene") or ""),
                    "face_detected": float(public_face.get("confidence") or 0) > 0,
                    "_embedding": face["embedding"],
                    "_face": public_face,
                    "_route": route_public,
                })

    within_route: Dict[str, Any] = {}
    pair_lists: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        route_samples = samples[route]
        pairs: List[Dict[str, Any]] = []
        matrix: List[List[Any]] = []
        for left in route_samples:
            matrix.append([
                _round(_distance(motor, left["_embedding"], right["_embedding"]))
                for right in route_samples
            ])
        for left_index, left in enumerate(route_samples):
            for right in route_samples[left_index + 1:]:
                left_quality = left["_route"]["image_quality"]
                right_quality = right["_route"]["image_quality"]
                left_area = max(float(left["_face"].get("image_area_ratio") or 0), 1e-12)
                right_area = max(float(right["_face"].get("image_area_ratio") or 0), 1e-12)
                left_angle = left["_face"].get("eye_line_angle_degrees")
                right_angle = right["_face"].get("eye_line_angle_degrees")
                pairs.append({
                    "left_file": left["file"],
                    "right_file": right["file"],
                    "left_identity": left["identity"],
                    "right_identity": right["identity"],
                    "left_face_index": left["face_index"],
                    "right_face_index": right["face_index"],
                    "pair_class": _pair_class(left, right),
                    "both_detected_faces": bool(left["face_detected"] and right["face_detected"]),
                    "distance": _round(_distance(motor, left["_embedding"], right["_embedding"])),
                    "same_sequence": left["sequence"] == right["sequence"],
                    "left_sequence": left["sequence"],
                    "right_sequence": right["sequence"],
                    "pose_changed": left["pose_tag"] != right["pose_tag"],
                    "left_pose": left["pose_tag"],
                    "right_pose": right["pose_tag"],
                    "involves_extreme_exposure": (
                        left["illumination_tag"] != "normal"
                        or right["illumination_tag"] != "normal"
                    ),
                    "luminance_gap": _round(abs(
                        float(left_quality["mean_luminance"])
                        - float(right_quality["mean_luminance"])
                    )),
                    "face_area_log_gap": _round(abs(math.log(left_area / right_area))),
                    "eye_angle_gap_degrees": _round(_angle_gap(left_angle, right_angle)),
                })
        pair_lists[route] = pairs
        within_route[route] = {
            "labels": [_public_sample(sample) for sample in route_samples],
            "distance_matrix": matrix,
            "pairs": pairs,
            "summary": _comparison_summary(pairs, threshold),
            "condition_sensitivity": _condition_sensitivity(pairs),
        }

    preview_samples = samples["preview"]
    fullraw_samples = samples["fullraw"]
    cross_matrix = [
        [
            _round(_distance(motor, left["_embedding"], right["_embedding"]))
            for right in fullraw_samples
        ]
        for left in preview_samples
    ]
    cross_pairs: List[Dict[str, Any]] = []
    corresponding: List[Dict[str, Any]] = []
    fullraw_by_key = {
        (sample["file"].casefold(), sample.get("identity")): sample
        for sample in fullraw_samples
    }
    for left in preview_samples:
        for right in fullraw_samples:
            pair_class = _pair_class(left, right, cross=True)
            distance = _round(_distance(motor, left["_embedding"], right["_embedding"]))
            cross_pairs.append({
                "preview_file": left["file"],
                "fullraw_file": right["file"],
                "preview_identity": left["identity"],
                "fullraw_identity": right["identity"],
                "pair_class": pair_class,
                "distance": distance,
            })
        right = fullraw_by_key.get((left["file"].casefold(), left.get("identity")))
        if not right:
            continue
        left_box = left["_face"]["normalized_area"]
        right_box = right["_face"]["normalized_area"]
        left_center = (
            float(left_box["x"]) + float(left_box["w"]) / 2,
            float(left_box["y"]) + float(left_box["h"]) / 2,
        )
        right_center = (
            float(right_box["x"]) + float(right_box["w"]) / 2,
            float(right_box["y"]) + float(right_box["h"]) / 2,
        )
        left_angle = left["_face"].get("eye_line_angle_degrees")
        right_angle = right["_face"].get("eye_line_angle_degrees")
        identity = left.get("identity")
        preview_reference = preview_gallery = preview_top3 = None
        fullraw_reference = fullraw_gallery = fullraw_top3 = None
        if identity:
            preview_reference = left["_face"]["distances_to_references"][identity]["natural_reference"]
            fullraw_reference = right["_face"]["distances_to_references"][identity]["natural_reference"]
            preview_gallery_info = left["_face"]["distances_to_truth_gallery"][identity]
            fullraw_gallery_info = right["_face"]["distances_to_truth_gallery"][identity]
            preview_gallery = preview_gallery_info["min_distance"]
            preview_top3 = preview_gallery_info["top3_average"]
            fullraw_gallery = fullraw_gallery_info["min_distance"]
            fullraw_top3 = fullraw_gallery_info["top3_average"]

        def preference(preview_value: Any, fullraw_value: Any, epsilon: float = 0.01) -> str:
            if preview_value is None or fullraw_value is None:
                return "insufficient_data"
            difference = float(preview_value) - float(fullraw_value)
            if abs(difference) <= epsilon:
                return "tie"
            return "fullraw" if difference > 0 else "preview"

        corresponding.append({
            "file": left["file"],
            "identity": identity,
            "scene": left["scene"],
            "sequence": left["sequence"],
            "embedding_distance_preview_vs_fullraw": _round(
                _distance(motor, left["_embedding"], right["_embedding"])
            ),
            "bbox_iou_normalized": _round(_normalized_iou(left_box, right_box)),
            "bbox_center_shift_normalized": _round(math.hypot(
                left_center[0] - right_center[0], left_center[1] - right_center[1]
            )),
            "face_area_ratio_preview": left["_face"]["image_area_ratio"],
            "face_area_ratio_fullraw": right["_face"]["image_area_ratio"],
            "confidence_preview": left["_face"]["confidence"],
            "confidence_fullraw": right["_face"]["confidence"],
            "face_detected_preview": left["face_detected"],
            "face_detected_fullraw": right["face_detected"],
            "eye_angle_delta_degrees": _round(_angle_gap(left_angle, right_angle)),
            "orientation_preview": _orientation(left["_route"]["image_size"]),
            "orientation_fullraw": _orientation(right["_route"]["image_size"]),
            "orientation_match": (
                _orientation(left["_route"]["image_size"])
                == _orientation(right["_route"]["image_size"])
            ),
            "mean_luminance_preview": left["_route"]["image_quality"]["mean_luminance"],
            "mean_luminance_fullraw": right["_route"]["image_quality"]["mean_luminance"],
            "natural_reference_distance_preview": preview_reference,
            "natural_reference_distance_fullraw": fullraw_reference,
            "truth_gallery_min_preview": preview_gallery,
            "truth_gallery_min_fullraw": fullraw_gallery,
            "truth_gallery_top3_preview": preview_top3,
            "truth_gallery_top3_fullraw": fullraw_top3,
            "preferred_route_by_reference": preference(preview_reference, fullraw_reference),
            "preferred_route_by_gallery": preference(preview_top3, fullraw_top3),
        })

    cross_summary = {
        "corresponding_embedding_distance": _distribution(
            row["embedding_distance_preview_vs_fullraw"] for row in corresponding
        ),
        "bbox_iou": _distribution(row["bbox_iou_normalized"] for row in corresponding),
        "bbox_center_shift": _distribution(
            row["bbox_center_shift_normalized"] for row in corresponding
        ),
        "eye_angle_delta": _distribution(
            row["eye_angle_delta_degrees"] for row in corresponding
        ),
        "orientation_mismatch_count": sum(not row["orientation_match"] for row in corresponding),
        "preview_fallback_count": sum(not row["face_detected_preview"] for row in corresponding),
        "fullraw_fallback_count": sum(not row["face_detected_fullraw"] for row in corresponding),
        "corresponding_count": len(corresponding),
        "cross_pair_distributions": {
            pair_class: _distribution(
                pair["distance"] for pair in cross_pairs if pair["pair_class"] == pair_class
            )
            for pair_class in (
                "corresponding_file", "same_identity", "different_identity", "no_target_control"
            )
        },
    }

    sequences = sorted({sample["sequence"] for route in routes for sample in samples[route]})
    sequence_rows: List[Dict[str, Any]] = []
    for sequence in sequences:
        route_distributions: Dict[str, Any] = {}
        for route in routes:
            route_distributions[route] = _distribution(
                pair["distance"] for pair in pair_lists[route]
                if pair["pair_class"] == "same_identity"
                and pair.get("both_detected_faces", False)
                and pair["same_sequence"]
                and pair["left_sequence"] == sequence
            )
        preview_median = route_distributions["preview"]["median"]
        fullraw_median = route_distributions["fullraw"]["median"]
        if preview_median is None or fullraw_median is None:
            preferred = "insufficient_data"
        elif abs(float(preview_median) - float(fullraw_median)) <= 0.01:
            preferred = "tie"
        else:
            preferred = "preview" if preview_median < fullraw_median else "fullraw"
        sequence_rows.append({
            "sequence": sequence,
            "preview": route_distributions["preview"],
            "fullraw": route_distributions["fullraw"],
            "preferred_route_by_internal_coherence": preferred,
        })

    return {
        "schema_version": 1,
        "purpose": "Diagnóstico A/B del Módulo 2; no interviene en clasificación.",
        "threshold_used_only_for_measurement": threshold,
        "within_route": within_route,
        "cross_route": {
            "preview_labels": [_public_sample(sample) for sample in preview_samples],
            "fullraw_labels": [_public_sample(sample) for sample in fullraw_samples],
            "distance_matrix": cross_matrix,
            "pairs": cross_pairs,
            "corresponding_photos": corresponding,
            "summary": cross_summary,
        },
        "sequence_comparison": sequence_rows,
        "limitations": [
            "El conjunto contiene dos identidades humanas y ninguna fotografía grupal.",
            "Las etiquetas de postura son categorías de escena, no estimaciones biométricas de pose 3D.",
            "Los controles sin persona se reportan separados de las parejas de humanos distintos.",
            "Ninguna preferencia de ruta modifica parámetros o decisiones del clasificador.",
        ],
    }


def measure_cr3_manifest(
    motor: Any,
    manifest: Dict[str, Any],
    source_root: Path,
    DeepFace: Any,
    progress_callback: ProgressCallback = None,
    include_representation_analysis: bool = False,
) -> Dict[str, Any]:
    """Mide preview y Full RAW sin cambiar ninguna decisión del motor."""
    verified = verify_manifest_files(manifest, source_root)
    model_name = str(manifest.get("model_name") or "ArcFace")
    detector_backend = str(manifest.get("detector_backend") or "retinaface")
    routes = ("preview", "fullraw")
    internal: Dict[str, Dict[str, Dict[str, Any]]] = {route: {} for route in routes}
    total_steps = len(verified) * len(routes)
    step = 0

    for item in verified:
        image_path = item["path"]
        for route in routes:
            step += 1
            if progress_callback:
                progress_callback({
                    "stage": "cr3_measurements",
                    "current": step,
                    "total": total_steps,
                    "percent": int(step * 100 / total_steps),
                    "message": f"Midiendo {route} {step}/{total_steps}: {image_path.name}",
                })
            if route == "preview":
                decode_path, status = motor._cr2_to_jpeg(image_path)
                cache_variant = ""
            else:
                decode_path, status = motor._cr3_fullraw_to_jpeg(image_path)
                cache_variant = motor.CR3_FULLRAW_CACHE_VARIANT
            faces: Optional[List[Dict[str, Any]]] = None
            image_size = (0, 0)
            if decode_path is not None:
                image_size = _route_image_size(decode_path)
                faces = motor._get_all_face_embeddings(
                    image_path,
                    model_name=model_name,
                    detector_backend=detector_backend,
                    DeepFace=DeepFace,
                    cache_variant=cache_variant,
                    decode_path_override=decode_path,
                )
            internal[route][item["file"]] = {
                "decode_status": status,
                "decode_path": decode_path,
                "image_size": image_size,
                "image_quality": _image_quality(decode_path) if decode_path is not None else None,
                "faces": faces,
            }

    identities = {item["id"]: item for item in manifest["identities"]}
    reference_vectors: Dict[str, Dict[str, Dict[str, Optional[List[float]]]]] = {
        route: {} for route in routes
    }
    for route in routes:
        for identity, definition in identities.items():
            reference_vectors[route][identity] = {}
            for kind in ("natural_reference", "control_reference"):
                filename = definition.get(kind)
                record = internal[route].get(filename) if filename else None
                primary = _primary_face((record or {}).get("faces") or [])
                reference_vectors[route][identity][kind] = (
                    primary.get("embedding") if primary else None
                )

    selected_truth_faces: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {
        route: defaultdict(dict) for route in routes
    }
    public_photos: List[Dict[str, Any]] = []
    route_rows: Dict[str, List[Dict[str, Any]]] = {route: [] for route in routes}

    for item in verified:
        public = {
            "file": item["file"],
            "sha256": item["sha256"],
            "target_identities": item["target_identities"],
            "companion_identities": item["companion_identities"],
            "no_target": bool(item["no_target"]),
            "routes": {},
        }
        for route in routes:
            record = internal[route][item["file"]]
            faces = record.get("faces") or []
            image_size = record["image_size"]
            face_rows: List[Dict[str, Any]] = []
            for index, face in enumerate(faces):
                face_row = _face_public(face, image_size, index)
                distances: Dict[str, Any] = {}
                for identity in identities:
                    distances[identity] = {}
                    for kind, vector in reference_vectors[route][identity].items():
                        distances[identity][kind] = (
                            _round(_distance(motor, face["embedding"], vector)) if vector else None
                        )
                face_row["distances_to_references"] = distances
                face_rows.append(face_row)

            best_identity = None
            best_face_index = None
            best_distance = None
            candidates: List[tuple[float, str, int]] = []
            for index, face in enumerate(faces):
                for identity in identities:
                    vector = reference_vectors[route][identity].get("natural_reference")
                    if vector:
                        candidates.append((_distance(motor, face["embedding"], vector), identity, index))
            candidates.sort(key=lambda value: (value[0], value[1], value[2]))
            if candidates:
                best_distance, candidate_identity, best_face_index = candidates[0]
                if best_distance <= 0.28:
                    best_identity = candidate_identity
            second_distance = candidates[1][0] if len(candidates) > 1 else None

            for identity in item["target_identities"]:
                natural = reference_vectors[route][identity].get("natural_reference")
                if faces:
                    chosen = min(
                        faces,
                        key=lambda face: _distance(motor, face["embedding"], natural)
                        if natural else -float((face.get("facial_area") or {}).get("w", 0))
                        * float((face.get("facial_area") or {}).get("h", 0)),
                    )
                    selected_truth_faces[route][identity][item["file"]] = chosen

            route_public = {
                "decode_status": record["decode_status"],
                "image_size": {"width": image_size[0], "height": image_size[1]},
                "image_quality": record["image_quality"],
                "face_count": len(faces),
                "faces": face_rows,
                "predicted_identity": best_identity,
                "best_reference_distance": _round(best_distance),
                "second_reference_distance": _round(second_distance),
                "reference_margin": _round(second_distance - best_distance)
                if best_distance is not None and second_distance is not None else None,
            }
            public["routes"][route] = route_public
            route_rows[route].append({
                "file": item["file"],
                "target_identities": item["target_identities"],
                "predicted_identity": best_identity,
            })
        public_photos.append(public)

    # Galería de evaluación oracle/leave-one-out: diagnostica cohesión posible,
    # no representa alimentadores reales ni cambia decisiones de producción.
    for public in public_photos:
        for route in routes:
            faces = internal[route][public["file"]].get("faces") or []
            for face_index, face in enumerate(faces):
                gallery_distances: Dict[str, Any] = {}
                for identity in identities:
                    anchors = [
                        anchor["embedding"]
                        for filename, anchor in selected_truth_faces[route][identity].items()
                        if filename != public["file"]
                    ]
                    distances = sorted(_distance(motor, face["embedding"], anchor) for anchor in anchors)
                    gallery_distances[identity] = {
                        "support_count": len(distances),
                        "min_distance": _round(distances[0]) if distances else None,
                        "top3_average": _round(sum(distances[:3]) / len(distances[:3])) if distances else None,
                    }
                public["routes"][route]["faces"][face_index]["distances_to_truth_gallery"] = gallery_distances

    summaries: Dict[str, Any] = {}
    for route in routes:
        summaries[route] = {
            "decoded": sum(1 for value in internal[route].values() if value["decode_path"] is not None),
            "with_faces": sum(1 for value in internal[route].values() if value.get("faces")),
            "with_detected_faces": sum(
                1 for value in internal[route].values()
                if any(float(face.get("face_confidence") or 0) > 0 for face in (value.get("faces") or []))
            ),
            "fallback_only": sum(
                1 for value in internal[route].values()
                if value.get("faces")
                and not any(float(face.get("face_confidence") or 0) > 0 for face in value["faces"])
            ),
            "total_faces": sum(len(value.get("faces") or []) for value in internal[route].values()),
            "direct_natural_reference": _metric_counts(route_rows[route], identities),
        }

    result = {
        "schema_version": 1,
        "purpose": (
            "Diagnóstico CR3 Módulos 1 y 2; no interviene en clasificación."
            if include_representation_analysis
            else "Diagnóstico CR3 Módulo 1; no interviene en clasificación."
        ),
        "model_name": model_name,
        "detector_backend": detector_backend,
        "direct_threshold": 0.28,
        "gallery_definition": "truth_leave_one_out_diagnostic_only",
        "source_root": str(source_root),
        "identity_count": len(identities),
        "photo_count": len(public_photos),
        "summaries": summaries,
        "photos": public_photos,
    }
    if include_representation_analysis:
        result["representation_analysis"] = _build_representation_analysis(
            motor,
            verified,
            internal,
            selected_truth_faces,
            public_photos,
            threshold=0.28,
        )
    return result


def evaluate_report_assignments(
    manifest: Dict[str, Any], report: Dict[str, Any], run_name: str
) -> Dict[str, Any]:
    manifest_by_file = {item["file"].casefold(): item for item in manifest["photos"]}
    predictions: Dict[str, List[str]] = defaultdict(list)
    unknown_deliveries: List[Dict[str, str]] = []
    for identity, paths in (report.get("fotos_por_persona") or {}).items():
        for raw_path in paths or []:
            filename = Path(raw_path).name
            key = filename.casefold()
            if key not in manifest_by_file:
                unknown_deliveries.append({"identity": identity, "file": filename})
                continue
            predictions[key].append(identity)

    rows: List[Dict[str, Any]] = []
    duplicate_assignments: List[Dict[str, Any]] = []
    for item in manifest["photos"]:
        assigned = sorted(set(predictions.get(item["file"].casefold(), [])))
        if len(assigned) > 1:
            duplicate_assignments.append({"file": item["file"], "identities": assigned})
        rows.append({
            "file": item["file"],
            "target_identities": item["target_identities"],
            "predicted_identity": assigned[0] if len(assigned) == 1 else None,
            "all_assignments": assigned,
        })
    identities = [item["id"] for item in manifest["identities"]]
    metrics = _metric_counts(rows, identities)
    return {
        "run_name": run_name,
        "report_path": report.get("report_path") or report.get("report_files", {}).get("json"),
        "metrics": metrics,
        "duplicate_assignments": duplicate_assignments,
        "unknown_deliveries": unknown_deliveries,
        "rows": rows,
    }
