"""
Workspace location resolution for FaceSync AI.

Resolves natural folder/file references to known relative paths inside the
project. It does not execute tools and does not weaken SecurityManager.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class LocationResolution:
    success: bool = False
    query: str = ""
    resolved_path: str = ""
    relative_path: str = ""
    kind: str = "unknown"
    confidence: float = 0.0
    ambiguous: bool = False
    candidates: List[str] = field(default_factory=list)
    message: str = ""
    location_field: str = ""

    def model_dump(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "query": self.query,
            "resolved_path": self.resolved_path,
            "relative_path": self.relative_path,
            "kind": self.kind,
            "confidence": self.confidence,
            "ambiguous": self.ambiguous,
            "candidates": list(self.candidates),
            "message": self.message,
            "location_field": self.location_field,
        }


class WorkspaceLocationResolver:
    CONTEXT_CURRENT = {"esta carpeta", "esa carpeta", "ahi", "alli", "aqui", "aca", "dentro de esta"}
    CONTEXT_LAST = {"ultima carpeta", "la ultima carpeta", "lo ultimo que creaste", "carpeta que acabas de crear"}

    def resolve(self, query: Any, system_state: Any, kind: str = "unknown") -> LocationResolution:
        state = self._state_dict(system_state)
        raw = self._text(query)
        cleaned = self.clean_query(raw)
        root = self._text(state.get("project_root") or state.get("workspace_actual"))

        contextual = self._contextual(cleaned, state, root)
        if contextual:
            return contextual

        if not cleaned:
            return LocationResolution(False, raw, kind=kind, message="Referencia vacia.")

        roots = self._roots_list(state, root)

        # Barrera central de ambiguedad. Antes de confiar en listas de contexto
        # (que pueden estar truncadas o desactualizadas), consulta las rutas
        # reales de TODAS las raices. Nunca toma la primera coincidencia.
        existing = self._existing_matches(cleaned, roots, kind)
        if len(existing) == 1:
            return self._success(raw, existing[0], root, kind, 1.0)
        if len(existing) > 1:
            return self._ambiguity(raw, cleaned, kind, existing)

        candidates = self._existing_candidates(self._candidates(state, kind), roots, kind)

        similar = self._contains_matches(cleaned, candidates)
        if len(similar) == 1:
            return LocationResolution(
                False,
                raw,
                kind=kind,
                confidence=0.68,
                ambiguous=True,
                candidates=similar,
                message=f"No encontre '{cleaned}'. Te refieres a '{similar[0]}'?",
            )
        if len(similar) > 1:
            return self._ambiguity(raw, cleaned, kind, similar)

        fuzzy = self._fuzzy_matches(cleaned, candidates)
        if fuzzy:
            best, best_score = fuzzy[0]
            second_score = fuzzy[1][1] if len(fuzzy) > 1 else 0.0
            close = [name for name, score in fuzzy if best_score - score < 0.08 and score >= 0.70]
            if len(close) > 1:
                return self._ambiguity(raw, cleaned, kind, close)
            if best_score >= 0.95:
                return self._success(raw, best, root, kind, best_score)
            if best_score >= 0.85 and best_score - second_score >= 0.08:
                return self._success(raw, best, root, kind, best_score)
            if best_score >= 0.70:
                return LocationResolution(
                    False,
                    raw,
                    kind=kind,
                    confidence=best_score,
                    ambiguous=True,
                    candidates=close or [best],
                    message=f"Te refieres a '{best}'?",
                )

        return LocationResolution(False, raw, kind=kind, message=f"No encontre '{cleaned}' en el workspace.")

    @classmethod
    def _ambiguity(cls, raw: str, cleaned: str, kind: str, candidates: Iterable[str]) -> LocationResolution:
        choices = cls._dedupe([str(item) for item in candidates])[:8]
        lines = [f"Encontre varias ubicaciones para '{cleaned}':"]
        lines.extend(f"{index}. {candidate}" for index, candidate in enumerate(choices, start=1))
        lines.append("Cual quieres usar?")
        return LocationResolution(
            False,
            raw,
            kind=kind,
            confidence=0.60,
            ambiguous=True,
            candidates=choices,
            message="\n".join(lines),
        )

    @classmethod
    def _existing_matches(cls, cleaned: str, roots: List[str], kind: str) -> List[str]:
        """Devuelve todas las coincidencias exactas existentes.

        La salida usa rutas absolutas para que una seleccion posterior quede
        ligada a un objeto inequivoco incluso en workspaces con varias raices.
        """
        if not cleaned:
            return []
        wanted = cls._norm(Path(cleaned).name)
        has_separator = "/" in cleaned or "\\" in cleaned
        found: List[str] = []

        direct = Path(cleaned).expanduser()
        if direct.is_absolute() and cls._kind_matches(direct, kind):
            found.append(str(direct.resolve(strict=False)))

        for root_text in roots:
            root = Path(root_text).expanduser().resolve(strict=False)
            if not root.is_dir():
                continue

            if kind in {"folder", "unknown"} and cls._norm(root.name) == cls._norm(cleaned):
                found.append(str(root))

            relative = (root / cleaned).resolve(strict=False)
            try:
                relative.relative_to(root)
            except Exception:
                relative = None
            if relative is not None and cls._kind_matches(relative, kind):
                found.append(str(relative))

            try:
                for candidate in root.rglob("*"):
                    if cls._norm(candidate.name) != wanted or not cls._kind_matches(candidate, kind):
                        continue
                    if has_separator:
                        try:
                            relative_norm = cls._norm(str(candidate.relative_to(root)).replace("\\", "/"))
                        except Exception:
                            continue
                        cleaned_norm = cls._norm(cleaned.replace("\\", "/"))
                        if relative_norm != cleaned_norm and not relative_norm.endswith("/" + cleaned_norm):
                            continue
                    found.append(str(candidate.resolve(strict=False)))
            except Exception:
                continue

        return cls._dedupe(found)

    @classmethod
    def _existing_candidates(cls, candidates: Iterable[str], roots: List[str], kind: str) -> List[str]:
        result: List[str] = []
        for value in candidates:
            text = cls._text(value)
            if not text:
                continue
            path = Path(text).expanduser()
            if path.is_absolute() and cls._kind_matches(path, kind):
                result.append(str(path.resolve(strict=False)))
                continue
            for root_text in roots:
                candidate = (Path(root_text).expanduser().resolve(strict=False) / text).resolve(strict=False)
                if cls._kind_matches(candidate, kind):
                    result.append(str(candidate))
        return cls._dedupe(result)

    @staticmethod
    def _kind_matches(path: Path, kind: str) -> bool:
        if kind == "folder":
            return path.is_dir()
        if kind == "file":
            return path.is_file()
        return path.exists()

    @classmethod
    def _match_workspace_root(cls, raw: str, cleaned: str, roots: List[str]) -> Optional[LocationResolution]:
        """Resuelve cuando el usuario nombra una carpeta RAIZ del workspace
        (p.ej. 'FRANK'). Compara por nombre normalizado contra cada raiz."""
        norm = cls._norm(cleaned)
        if not norm:
            return None
        exact = [r for r in roots if cls._norm(Path(r).name) == norm]
        if len(exact) == 1:
            abs_path = str(Path(exact[0]).resolve(strict=False))
            return LocationResolution(True, raw, abs_path, abs_path, "folder", 0.99, False, [],
                                      "Carpeta raiz del workspace.")
        if len(exact) > 1:
            candidates = [Path(r).name for r in exact]
            return LocationResolution(
                False, raw, kind="folder", confidence=0.6, ambiguous=True, candidates=candidates,
                message=f"Hay varias raices llamadas '{cleaned}'. Cual quieres usar?",
            )
        return None

    @classmethod
    def _roots_list(cls, state: Dict[str, Any], root: str) -> List[str]:
        roots = [cls._text(r) for r in cls._list(state.get("workspace_roots")) if cls._text(r)]
        if root and root not in roots:
            roots = [root] + roots
        return cls._dedupe(roots)

    @classmethod
    def _multi_root_resolve(cls, raw: str, cleaned: str, kind: str, roots: List[str]) -> Optional[LocationResolution]:
        matches: List[tuple] = []  # (root, rel, abs)
        seen = set()
        for r in roots:
            rel = cls._relative_exists(cleaned, r, kind) or cls._unique_basename_exists(cleaned, r, kind)
            if not rel:
                continue
            abs_path = str((Path(r) / rel).resolve(strict=False))
            if abs_path in seen:
                continue
            seen.add(abs_path)
            matches.append((r, rel, abs_path))
        if not matches:
            return None
        if len(matches) == 1:
            abs_path = matches[0][2]
            return LocationResolution(True, raw, abs_path, abs_path, kind, 0.97, False, [],
                                      "Ubicacion resuelta (workspace multi-root).")
        candidates = [f"{Path(r).name}/{rel}" for r, rel, _ in matches[:6]]
        return LocationResolution(
            False, raw, kind=kind, confidence=0.6, ambiguous=True, candidates=candidates,
            message=f"Encontre '{cleaned}' en varias carpetas: {', '.join(candidates)}. Cual quieres usar?",
        )

    def resolve_args(self, intent: str, args: Dict[str, Any], system_state: Any) -> tuple[Dict[str, Any], Optional[LocationResolution]]:
        resolved = dict(args or {})
        fields = self._fields_for_intent(intent, resolved)
        for field, kind, required_existing in fields:
            value = resolved.get(field)
            if value in (None, ""):
                continue
            result = self.resolve(value, system_state, kind=self._kind_hint(kind, field, system_state))
            if result.success:
                resolved[field] = result.relative_path
                continue
            if required_existing and (result.ambiguous or result.candidates or result.message):
                result.location_field = field
                return resolved, result
        return resolved, None

    @classmethod
    def _kind_hint(cls, kind: str, location_field: str, system_state: Any) -> str:
        if kind != "unknown" or location_field != "target":
            return kind
        state = cls._state_dict(system_state)
        text = cls._norm(state.get("_user_text") or state.get("last_user_text"))
        tokens = set(text.split())
        if tokens.intersection({"carpeta", "carpetas", "directorio", "directorios"}):
            return "folder"
        if tokens.intersection({"archivo", "archivos", "documento", "documentos"}):
            return "file"
        return kind

    @classmethod
    def clean_query(cls, value: Any) -> str:
        text = cls._text(value)
        patterns = [
            r"^(?:adentro|dentro)\s+de\s+(?:la\s+)?",
            r"^en\s+(?:la\s+)?",
            r"^(?:la\s+|el\s+)?(?:carpeta|archivo)\s+de\s+",
            r"^(?:la\s+|el\s+)?(?:carpeta|archivo)\s+",
        ]
        changed = True
        while changed:
            before = text
            for pattern in patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            changed = text != before
        return text.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _fields_for_intent(cls, intent: str, args: Dict[str, Any]) -> List[tuple[str, str, bool]]:
        del args
        intent = str(intent or "")
        fields: List[tuple[str, str, bool]] = []
        if intent in {"move_item", "copy_item", "rename_item", "delete_item"}:
            fields.append(("target", "unknown", True))
        if intent in {"read_document", "create_folders_from_table", "create_folders_from_excel", "run_reference_face_matching", "classify_photos_by_reference"}:
            fields.append(("table_path", "file", True))
        if intent in {"run_reference_face_matching", "classify_photos_by_reference"}:
            fields.append(("source_folder", "folder", True))
        if intent in {"create_folder", "create_file", "create_multiple_folders", "create_folders_from_table", "create_folders_from_excel", "run_reference_face_matching", "classify_photos_by_reference", "move_item", "copy_item"}:
            fields.append(("destination_folder", "folder", True))
        return fields

    @classmethod
    def _candidates(cls, state: Dict[str, Any], kind: str) -> List[str]:
        values: List[str] = []
        if kind in {"folder", "unknown"}:
            values.extend(cls._list(state.get("available_folders")))
        if kind in {"file", "unknown"}:
            values.extend(cls._list(state.get("available_files")))
        return cls._dedupe([cls._to_relative(item, state) for item in values if item])

    @classmethod
    def _contextual(cls, cleaned: str, state: Dict[str, Any], root: str) -> Optional[LocationResolution]:
        norm = cls._norm(cleaned)
        if norm in {cls._norm(item) for item in cls.CONTEXT_CURRENT}:
            active = cls._text(state.get("active_path"))
            if active:
                rel = cls._relative_from_root(active, root)
                return cls._success(cleaned, rel, root, "folder", 0.95)
        if norm in {cls._norm(item) for item in cls.CONTEXT_LAST}:
            last = state.get("last_created_item") or cls._last_list_item(state.get("last_created_items"))
            if last:
                return cls._success(cleaned, cls._text(last), root, "folder", 0.95)
        return None

    @classmethod
    def _success(cls, query: str, relative: str, root: str, kind: str, confidence: float) -> LocationResolution:
        rel = cls._clean_relative(relative, root)
        resolved = str((Path(root) / rel).resolve(strict=False)) if root and rel else rel
        return LocationResolution(True, query, resolved, rel, kind, confidence, False, [], "Ubicacion resuelta.")

    @classmethod
    def _relative_exists(cls, cleaned: str, root: str, kind: str) -> str:
        if not root or not cleaned:
            return ""
        candidate = (Path(root) / cleaned).resolve(strict=False)
        try:
            candidate.relative_to(Path(root).resolve(strict=False))
        except Exception:
            return ""
        if kind == "folder" and candidate.is_dir():
            return cleaned
        if kind == "file" and candidate.is_file():
            return cleaned
        if kind == "unknown" and candidate.exists():
            return cleaned
        return ""

    @classmethod
    def _unique_basename_exists(cls, cleaned: str, root: str, kind: str) -> str:
        if not root or not cleaned or "/" in cleaned or "\\" in cleaned:
            return ""
        root_path = Path(root).expanduser().resolve(strict=False)
        if not root_path.is_dir():
            return ""
        wanted = cls._norm(cleaned)
        matches: List[str] = []
        try:
            for candidate in root_path.rglob("*"):
                if kind == "folder" and not candidate.is_dir():
                    continue
                if kind == "file" and not candidate.is_file():
                    continue
                if cls._norm(candidate.name) == wanted:
                    matches.append(str(candidate.relative_to(root_path)).replace("\\", "/"))
        except Exception:
            return ""
        return matches[0] if len(matches) == 1 else ""

    @classmethod
    def _exact(cls, cleaned: str, candidates: Iterable[str]) -> str:
        return next((item for item in candidates if cls.clean_query(item) == cleaned), "")

    @classmethod
    def _case_insensitive(cls, cleaned: str, candidates: Iterable[str]) -> str:
        norm = cls._norm(cleaned)
        return next((item for item in candidates if cls._norm(cls.clean_query(item)) == norm), "")

    @classmethod
    def _contains_matches(cls, cleaned: str, candidates: Iterable[str]) -> List[str]:
        norm = cls._norm(cleaned)
        if not norm:
            return []
        matches = []
        for item in candidates:
            item_norm = cls._norm(item)
            name_norm = cls._norm(Path(str(item)).name)
            if norm in item_norm or norm in name_norm:
                matches.append(item)
        exact_name = [item for item in matches if cls._norm(Path(str(item)).name) == norm]
        return exact_name or cls._dedupe(matches)

    @classmethod
    def _fuzzy_matches(cls, cleaned: str, candidates: Iterable[str]) -> List[tuple[str, float]]:
        norm = cls._norm(cleaned)
        if not norm:
            return []
        ranked = []
        for item in candidates:
            item_norm = cls._norm(item)
            name_norm = cls._norm(Path(str(item)).name)
            score = max(
                difflib.SequenceMatcher(None, norm, item_norm).ratio(),
                difflib.SequenceMatcher(None, norm, name_norm).ratio(),
            )
            ranked.append((item, round(score, 4)))
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return [pair for pair in ranked if pair[1] >= 0.70]

    @staticmethod
    def _state_dict(state: Any) -> Dict[str, Any]:
        if isinstance(state, dict):
            result = dict(state)
        elif hasattr(state, "current_context"):
            result = dict(getattr(state, "current_context") or {})
        else:
            result = {}
        summary = result.get("context_summary")
        if isinstance(summary, dict):
            for key, value in summary.items():
                result.setdefault(key, value)
        return result

    @classmethod
    def _to_relative(cls, value: Any, state: Dict[str, Any]) -> str:
        root = cls._text(state.get("project_root") or state.get("workspace_actual"))
        return cls._clean_relative(cls._text(value), root)

    @staticmethod
    def _clean_relative(value: str, root: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if root:
            try:
                path = Path(text).expanduser().resolve(strict=False)
                root_path = Path(root).expanduser().resolve(strict=False)
                return str(path.relative_to(root_path)).replace("\\", "/")
            except Exception:
                pass
        return text.replace("\\", "/").strip("/")

    @staticmethod
    def _relative_from_root(value: str, root: str) -> str:
        if not root:
            return str(value or "")
        try:
            return str(Path(value).resolve(strict=False).relative_to(Path(root).resolve(strict=False))).replace("\\", "/")
        except Exception:
            return str(value or "")

    @staticmethod
    def _last_list_item(value: Any) -> str:
        if isinstance(value, list) and value:
            return str(value[-1])
        return ""

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

    @staticmethod
    def _norm(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9./\\\s-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _dedupe(values: Iterable[str]) -> List[str]:
        result = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result


__all__ = ["LocationResolution", "WorkspaceLocationResolver"]
