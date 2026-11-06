"""
Column resolution for FaceSync AI.

Resolves user column hints against available table columns using exact,
case-insensitive and difflib fuzzy matching. It never executes tools.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ColumnResolution:
    success: bool = False
    query: str = ""
    resolved_column: str = ""
    confidence: float = 0.0
    ambiguous: bool = False
    candidates: List[str] = field(default_factory=list)
    message: str = ""

    def model_dump(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "query": self.query,
            "resolved_column": self.resolved_column,
            "confidence": self.confidence,
            "ambiguous": self.ambiguous,
            "candidates": list(self.candidates),
            "message": self.message,
        }


class ColumnResolver:
    NAME_HINTS = {"nombre", "nombres", "persona", "personas", "alumno", "cliente", "participante", "heroe", "hero"}
    REF_HINTS = {"foto", "fot", "imagen", "referencia", "archivo", "codigo", "numero", "id"}
    SOFT_ALIASES = {
        "imagen": "foto",
        "imagenes": "foto",
        "fotografia": "foto",
        "fotografias": "foto",
        "hero": "heroe",
        "eroe": "heroe",
    }

    def resolve(self, query: Any, available_columns: Any, role: str = "unknown") -> ColumnResolution:
        raw = self._text(query)
        cleaned = self.clean_query(raw)
        columns = self._list(available_columns)
        if not cleaned:
            return ColumnResolution(False, raw, message="Columna vacia.")
        if not columns:
            return ColumnResolution(False, raw, message="No hay columnas disponibles.")

        exact = next((col for col in columns if col == cleaned), "")
        if exact:
            return ColumnResolution(True, raw, exact, 1.0, False, [], "Columna resuelta.")

        norm = self._norm(cleaned)
        case = next((col for col in columns if self._norm(col) == norm), "")
        if case:
            return ColumnResolution(True, raw, case, 0.98, False, [], "Columna resuelta.")

        ranked = self._rank(cleaned, columns, role)
        if not ranked:
            return ColumnResolution(False, raw, message=f"No encontre una columna parecida a '{cleaned}'.")
        best, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        close = [name for name, score in ranked if best_score - score < 0.08 and score >= 0.70]

        if best_score >= 0.95:
            return ColumnResolution(True, raw, best, best_score, False, [], "Columna resuelta por fuzzy.")
        if best_score >= 0.85 and best_score - second_score >= 0.08:
            return ColumnResolution(True, raw, best, best_score, False, [], "Columna resuelta por fuzzy.")
        if best_score >= 0.70:
            return ColumnResolution(
                False,
                raw,
                confidence=best_score,
                ambiguous=True,
                candidates=close or [best],
                message=f"Te refieres a la columna '{best}'?",
            )
        return ColumnResolution(False, raw, confidence=best_score, candidates=[best], message="No hay confianza suficiente para elegir columna.")

    def resolve_pair(self, name_column: Any, reference_column: Any, available_columns: Any) -> tuple[str, str, Optional[ColumnResolution]]:
        columns = self._list(available_columns)
        name = self.resolve(name_column, columns, role="name") if name_column else ColumnResolution(False, self._text(name_column))
        ref = self.resolve(reference_column, columns, role="reference") if reference_column else ColumnResolution(False, self._text(reference_column))

        resolved_name = name.resolved_column if name.success else self._text(name_column)
        resolved_ref = ref.resolved_column if ref.success else self._text(reference_column)
        if resolved_name and resolved_ref and self._norm(resolved_name) == self._norm(resolved_ref):
            repaired_name = self._probable_name_column(columns, exclude=resolved_ref)
            if repaired_name:
                return repaired_name, resolved_ref, None
            return resolved_name, resolved_ref, ColumnResolution(
                False,
                f"{name_column}/{reference_column}",
                confidence=0.0,
                ambiguous=True,
                candidates=columns,
                message="La columna de nombres y referencia son iguales. Cuales debo usar?",
            )

        if name_column and not name.success:
            return resolved_name, resolved_ref, name
        if reference_column and not ref.success:
            return resolved_name, resolved_ref, ref
        return resolved_name, resolved_ref, None

    @classmethod
    def clean_query(cls, value: Any) -> str:
        text = cls._text(value)
        text = re.sub(r"^(?:la\s+)?columna\s+", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"^columa\s+", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s+como\s+referencia(?:\s+facial)?$", "", text, flags=re.IGNORECASE).strip()
        return text.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _rank(cls, query: str, columns: List[str], role: str) -> List[tuple[str, float]]:
        qnorm = cls._norm(query)
        qtokens = set(qnorm.split())
        ranked = []
        for column in columns:
            cnorm = cls._norm(column)
            score = difflib.SequenceMatcher(None, qnorm, cnorm).ratio()
            ctokens = set(cnorm.split())
            if qtokens:
                overlap = len(qtokens & ctokens) / max(len(qtokens), 1)
                if overlap:
                    score = max(score, min(0.94, 0.74 + overlap * 0.20))
            score = max(score, cls._role_score(qtokens, ctokens, role))
            ranked.append((column, round(score, 4)))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    @classmethod
    def _role_score(cls, qtokens: set[str], ctokens: set[str], role: str) -> float:
        if role == "reference" and qtokens & cls.REF_HINTS and ctokens & {"foto", "imagen", "referencia", "archivo"}:
            return 0.90
        if role == "name" and qtokens & cls.NAME_HINTS and ctokens & cls.NAME_HINTS:
            return 0.88
        return 0.0

    @classmethod
    def _probable_name_column(cls, columns: List[str], exclude: str = "") -> str:
        exclude_norm = cls._norm(exclude)
        candidates = []
        for column in columns:
            if cls._norm(column) == exclude_norm:
                continue
            tokens = set(cls._norm(column).split())
            if tokens & cls.NAME_HINTS:
                candidates.append(column)
        return candidates[0] if len(candidates) == 1 else ""

    @classmethod
    def _norm(cls, value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9.\-/\\\s]+", " ", text)
        parts = [cls.SOFT_ALIASES.get(part, part) for part in text.split()]
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    @staticmethod
    def _list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value if item not in (None, "")]

    @staticmethod
    def _text(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text.lower() == "none" else text


__all__ = ["ColumnResolution", "ColumnResolver"]
