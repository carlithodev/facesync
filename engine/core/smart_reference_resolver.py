"""
SmartReferenceResolver — capa ADITIVA y previa al motor FaceSync.

Problema: en el Excel la referencia de un alumno puede ser solo un número (2159)
y en disco existir VARIOS archivos con ese número (IMG_2159 en ARTURO, FRANK,
RUBEN…, jpg/cr2, fotos familiares). Tomar el primero puede usar la cara
equivocada -> el motor clasifica "bien" pero con la persona incorrecta.

Filosofía: automático NO significa adivinar, pero TAMPOCO omitir de más.
  - 1 candidato            -> se usa (como antes), confianza 100.
  - varios candidatos      -> scoring por CONTEXTO (multi-carpeta origen):
        * dentro de carpeta origen seleccionada (peso fuerte)
        * DENSIDAD: la carpeta con más referencias del lote cerca de N gana
        * vecindad numérica (N±1/±2 presentes en la carpeta)
        * carpeta dominante (solo bonus, NO bloquea otras carpetas origen)
        * preferencia JPG/PNG sobre CR2
        * penaliza candidatos FUERA de las carpetas origen
    Se elige si score >= MIN_SCORE y hay margen >= MIN_MARGIN sobre el 2º.
    Si dos candidatos quedan realmente iguales -> ambigua (se omite y reporta).

Puro (sin I/O, sin disco, sin DeepFace). El wrapper del motor arma el índice de
archivos y el contexto. No toca motor, umbrales, embeddings, galería,
AntiCrossCheck, CR2 ni Drive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ======================================================================
# CONSTANTES CENTRALIZADAS (sin números mágicos dispersos)
# ======================================================================
SMART_REFERENCE_ENABLED = True

# Umbrales (más permisivos que la v1, pero con anti-empate firme).
SMART_REFERENCE_MIN_SCORE = 60          # score mínimo para elegir automáticamente
SMART_REFERENCE_MIN_MARGIN = 10         # margen mínimo sobre el 2º candidato

# Pesos del scoring (multi-carpeta origen).
SMART_REFERENCE_SOURCE_CONTEXT_POINTS = 35   # dentro de carpeta origen seleccionada
SMART_REFERENCE_SEQUENCE_POINTS = 25         # mayor densidad de refs del lote cerca de N
SMART_REFERENCE_NEIGHBOR_POINTS = 30         # N±1/±2 presentes en la carpeta
SMART_REFERENCE_DOMINANT_FOLDER_POINTS = 20  # carpeta dominante: BONUS, no condición
SMART_REFERENCE_FORMAT_POINTS = 10           # JPG/PNG preferido sobre CR2
SMART_REFERENCE_OUTSIDE_SOURCE_PENALTY = 40  # candidato fuera de carpetas origen
SMART_REFERENCE_SEQUENCE_WINDOW = 25         # ventana ± para densidad/secuencia

# VALIDACIÓN DE RETRATO (OpenCV Haar, NO el motor de reconocimiento):
# cuando un mismo número existe en carpetas distintas como PERSONAS distintas
# (cámaras de distintos fotógrafos cuyos números chocan), la referencia correcta
# es el RETRATO SOLO (1 cara) -así numeran las escuelas-; la foto familiar/grupal
# (varias caras) es mala referencia. Se prefiere la "sesión de retratos" y se
# rechaza la familiar. El conteo de caras lo hace el INTEGRADOR con OpenCV y lo
# pasa por contexto (este módulo sigue siendo puro). NO toca DeepFace/ArcFace/
# RetinaFace/umbrales/embeddings/clasificación.
SMART_REFERENCE_FACE_CHECK_ENABLED = True
SMART_REFERENCE_PORTRAIT_FOLDER_POINTS = 40   # carpeta = sesión de retratos (1 cara)
SMART_REFERENCE_SOLO_FACE_POINTS = 15         # la imagen candidata es retrato solo
SMART_REFERENCE_FAMILY_PENALTY = 35           # imagen con varias caras (familiar)
SMART_REFERENCE_NOFACE_PENALTY = 15           # imagen sin caras detectadas
SMART_REFERENCE_PORTRAIT_MIN_FRACTION = 0.5   # fracción para considerar "sesión de retratos"
SMART_REFERENCE_PORTRAIT_MIN_MARGIN = 0.2     # margen sobre la otra carpeta candidata

_PREFERRED_EXT = (".jpg", ".jpeg", ".png")


def extract_reference_number(value) -> str:
    """Último grupo de dígitos ('IMG_2159' -> '2159', '2159' -> '2159')."""
    nums = re.findall(r"\d+", str(value or ""))
    return nums[-1] if nums else ""


def _norm_folder(folder: str) -> str:
    return (folder or "").replace("\\", "/").strip("/").lower()


def folder_in_sources(folder: str, sources: Sequence[str]) -> bool:
    """True si `folder` es (o está dentro de) una carpeta origen seleccionada."""
    f = _norm_folder(folder)
    if not f:
        return False
    for s in sources or ():
        ss = _norm_folder(s)
        if ss and (f == ss or f.startswith(ss + "/") or ss.startswith(f + "/")):
            return True
    return False


@dataclass
class RefCandidate:
    path: str           # ruta absoluta (str)
    folder: str         # carpeta (relativa al workspace) que lo contiene
    ext: str            # extensión en minúscula, con punto
    faces: int = -1     # nº de caras (OpenCV); -1 = desconocido / no calculado

    @property
    def is_preferred(self) -> bool:
        return self.ext.lower() in _PREFERRED_EXT


@dataclass
class RefContext:
    number: str = ""                                              # número de referencia actual
    dominant_folder: str = ""                                     # carpeta dominante (bonus)
    selected_sources: List[str] = field(default_factory=list)    # carpetas origen seleccionadas
    folder_numbers: Dict[str, Set[str]] = field(default_factory=dict)  # carpeta -> nºs del lote presentes
    multi_source: bool = False                                   # 2+ carpetas origen
    folder_portrait_score: Dict[str, float] = field(default_factory=dict)  # carpeta(norm) -> fracción retratos


@dataclass
class RefResolution:
    status: str                       # resuelta_automaticamente | referencia_unica |
                                      # referencia_ambigua | referencia_no_encontrada
    chosen: Optional[str]
    score: int
    reasons: List[str] = field(default_factory=list)
    candidates: List[str] = field(default_factory=list)
    candidate_scores: List[dict] = field(default_factory=list)   # detalle por candidato
    dominant_folder: str = ""
    neighbors_used: List[str] = field(default_factory=list)


class SmartReferenceResolver:
    """Decide la referencia correcta a partir de candidatos + contexto. Puro."""

    def __init__(self, min_score: int = SMART_REFERENCE_MIN_SCORE,
                 min_margin: int = SMART_REFERENCE_MIN_MARGIN,
                 window: int = SMART_REFERENCE_SEQUENCE_WINDOW):
        self.min_score = int(min_score)
        self.min_margin = int(min_margin)
        self.window = int(window)

    # ------------------------------------------------------------------
    def _local_density(self, folder: str, n: Optional[int], ctx: RefContext) -> int:
        """Cuántos números del lote (Excel) hay en `folder` dentro de ±window de N
        (excluye N). Mide el 'clúster' del salón en esa carpeta."""
        if n is None:
            return 0
        nums = ctx.folder_numbers.get(_norm_folder(folder), set())
        count = 0
        for m in nums:
            try:
                mi = int(m)
            except (TypeError, ValueError):
                continue
            if mi != n and abs(mi - n) <= self.window:
                count += 1
        return count

    def _score(self, cand: RefCandidate, ctx: RefContext, n: Optional[int],
               density_leaders: Set[str], portrait_leader: Optional[str]) -> Tuple[int, List[str], List[str], bool]:
        score = 0
        reasons: List[str] = []
        cf = _norm_folder(cand.folder)
        nums = ctx.folder_numbers.get(cf, set())
        in_source = folder_in_sources(cand.folder, ctx.selected_sources)

        if in_source:
            score += SMART_REFERENCE_SOURCE_CONTEXT_POINTS
            reasons.append("dentro de carpeta origen seleccionada")
        else:
            score -= SMART_REFERENCE_OUTSIDE_SOURCE_PENALTY
            reasons.append("fuera de carpetas origen (penalizado)")

        # RETRATO (OpenCV, no el motor): cuando los candidatos son personas
        # distintas con el mismo número (cámaras que chocan), la referencia buena
        # es el retrato solo; la familiar se rechaza. La señal de CARPETA (fracción
        # de retratos, promediada sobre una muestra) es FIABLE; el conteo por
        # imagen es RUIDOSO, así que al candidato de la carpeta-retrato líder NO se
        # le castiga por una mala cuenta puntual (se confía en la carpeta).
        is_portrait_leader = (portrait_leader is not None and cf == portrait_leader)
        if is_portrait_leader:
            score += SMART_REFERENCE_PORTRAIT_FOLDER_POINTS
            reasons.append("carpeta = sesión de retratos (1 cara por foto)")
        if cand.faces == 1:
            score += SMART_REFERENCE_SOLO_FACE_POINTS
            reasons.append("retrato solo (1 cara)")
        elif not is_portrait_leader and cand.faces is not None and cand.faces > 1:
            score -= SMART_REFERENCE_FAMILY_PENALTY
            reasons.append(f"foto familiar/grupal ({cand.faces} caras) - mala referencia")
        elif not is_portrait_leader and cand.faces == 0:
            score -= SMART_REFERENCE_NOFACE_PENALTY
            reasons.append("sin caras detectadas")

        if cand.is_preferred:
            score += SMART_REFERENCE_FORMAT_POINTS
            reasons.append("formato JPG/PNG preferido")

        used: List[str] = []
        if n is not None:
            for delta in (-1, 1, -2, 2):
                if str(n + delta) in nums:
                    used.append(str(n + delta))
            if used:
                score += SMART_REFERENCE_NEIGHBOR_POINTS
                reasons.append("vecinos " + ", ".join(sorted(used, key=int)) + " en la carpeta")

        if cf in density_leaders:
            score += SMART_REFERENCE_SEQUENCE_POINTS
            reasons.append(f"mayor densidad de referencias del lote cerca de {ctx.number}")

        if ctx.dominant_folder and cf == _norm_folder(ctx.dominant_folder):
            score += SMART_REFERENCE_DOMINANT_FOLDER_POINTS
            reasons.append("carpeta dominante del lote (bonus)")

        return max(0, min(100, score)), reasons, used, in_source

    # ------------------------------------------------------------------
    def resolve(self, candidates: List[RefCandidate], ctx: RefContext) -> RefResolution:
        paths = [c.path for c in candidates]

        if not candidates:
            return RefResolution("referencia_no_encontrada", None, 0,
                                 ["sin candidatos"], paths, [], ctx.dominant_folder)

        if len(candidates) == 1:
            return RefResolution("referencia_unica", candidates[0].path, 100,
                                 ["referencia única"], paths,
                                 [{"path": candidates[0].path, "folder": candidates[0].folder,
                                   "score": 100, "in_source": True, "reasons": ["referencia única"]}],
                                 ctx.dominant_folder)

        try:
            n = int(ctx.number)
        except (TypeError, ValueError):
            n = None

        # Líder de densidad: la carpeta candidata con MÁS refs del lote cerca de N,
        # solo si es un líder ÚNICO (si empatan, nadie recibe el bonus -> conservador).
        densities = {_norm_folder(c.folder): self._local_density(c.folder, n, ctx) for c in candidates}
        density_leaders: Set[str] = set()
        if densities:
            maxd = max(densities.values())
            if maxd > 0:
                top = [f for f, d in densities.items() if d == maxd]
                if len(top) == 1:
                    density_leaders = set(top)

        # Líder de RETRATO: la carpeta candidata que es claramente la "sesión de
        # retratos" (mayor fracción de fotos con 1 cara), con margen sobre la otra.
        portrait_leader: Optional[str] = None
        ps = ctx.folder_portrait_score or {}
        if ps:
            cand_folders = {_norm_folder(c.folder) for c in candidates}
            ranked = sorted(((ps[f], f) for f in cand_folders if f in ps), reverse=True)
            if ranked:
                top_s, top_f = ranked[0]
                second_s = ranked[1][0] if len(ranked) > 1 else -1.0
                if (top_s >= SMART_REFERENCE_PORTRAIT_MIN_FRACTION
                        and (top_s - second_s) >= SMART_REFERENCE_PORTRAIT_MIN_MARGIN):
                    portrait_leader = top_f

        scored: List[Tuple[int, List[str], List[str], bool, RefCandidate]] = []
        for cand in candidates:
            s, r, used, in_src = self._score(cand, ctx, n, density_leaders, portrait_leader)
            scored.append((s, r, used, in_src, cand))
        scored.sort(key=lambda t: (-t[0], t[4].path))

        candidate_scores = [
            {"path": c.path, "folder": c.folder, "score": s, "in_source": in_src, "reasons": r}
            for (s, r, used, in_src, c) in scored
        ]

        best_score, best_reasons, best_used, _bsrc, best_cand = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else -1

        if best_score < self.min_score:
            return RefResolution(
                "referencia_ambigua", None, best_score,
                [f"confianza insuficiente (mejor score {best_score} < {self.min_score})"] + best_reasons,
                paths, candidate_scores, ctx.dominant_folder, best_used)

        if (best_score - second_score) < self.min_margin:
            return RefResolution(
                "referencia_ambigua", None, best_score,
                [f"empate técnico (margen {best_score - second_score} < {self.min_margin})"] + best_reasons,
                paths, candidate_scores, ctx.dominant_folder, best_used)

        return RefResolution("resuelta_automaticamente", best_cand.path, best_score,
                             best_reasons, paths, candidate_scores, ctx.dominant_folder, best_used)
