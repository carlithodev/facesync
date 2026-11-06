
"""
======================================================================
MÓDULO: SEARCH CAPABILITIES — FaceSync AI Tools
Archivo: tools/search_tools.py
======================================================================

Responsabilidad:
- Búsquedas inteligentes dentro del workspace.
- Indexación y localización rápida de archivos.
- Búsqueda semántica heurística.
- Detección de duplicados.
- Búsqueda por contenido interno.
- Preparado para agentes IA modernos.

Capacidades:
✔ Buscar archivos por nombre
✔ Buscar por extensión
✔ Buscar contenido dentro de archivos
✔ Búsqueda semántica básica
✔ Detección SHA256 de duplicados
✔ Sandbox seguro
✔ Integración futura con embeddings IA

======================================================================
"""
from __future__ import annotations

import os
import fnmatch
import hashlib
import logging

from pathlib import Path
from typing import Optional, Union, Dict, List, Any

from core.security import SecurityManager

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("FaceSync.SearchTools")


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SearchCapabilities:
    """
    Motor avanzado de búsqueda para agentes IA.

    Diseñado para:
    - Gemini
    - Claude
    - ChatGPT
    - Tool Calling
    - Sistemas autónomos

    Características:
    ✔ Búsqueda difusa
    ✔ Búsqueda por contenido
    ✔ Búsqueda heurística
    ✔ Detección de duplicados
    ✔ Sandbox protection
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        workspace_path: str,
        security_manager: Optional[SecurityManager] = None
    ):
        """
        Inicializa SearchCapabilities.

        Args:
            workspace_path:
                Workspace seguro.

            security_manager:
                Motor de seguridad compartido.
        """

        self.workspace_path = Path(
            workspace_path
        ).resolve()

        self.security = security_manager or SecurityManager(workspace_path=str(self.workspace_path))
        if Path(getattr(self.security, "workspace_path", self.workspace_path)).resolve() != self.workspace_path:
            self.security = SecurityManager(
                workspace_path=str(self.workspace_path),
                app_data_root=getattr(self.security, "app_data_path", None),
            )

    def set_project_root(self, project_root: str):
        self.workspace_path = Path(project_root).resolve()
        if hasattr(self.security, "set_project_root"):
            self.security.set_project_root(str(self.workspace_path))
        else:
            self.security = SecurityManager(workspace_path=str(self.workspace_path))

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    # ========================================================
    # SEGURIDAD
    # ========================================================

    def _resolve_secure_path(
        self,
        path: str
    ) -> Path:
        """
        Valida rutas sandbox.
        """

        secure_path = self.security.secure_path(
            str(path)
        )

        if not secure_path:
            raise PermissionError(
                f"Ruta insegura: {path}"
            )

        return Path(secure_path)

    # ========================================================
    # BUSCAR POR NOMBRE
    # ========================================================

    def search_by_name(
        self,
        pattern: str,
        root_dir: Optional[str] = None,
        extensions: Optional[List[str]] = None,
        recursive: bool = True
    ) -> Dict[str, Any]:
        """
        Busca archivos por nombre/patrón.

        Args:
            pattern:
                Patrón de búsqueda.

            root_dir:
                Carpeta raíz.

            extensions:
                Filtro de extensiones.

            recursive:
                Buscar recursivamente.

        Returns:
            Dict
        """

        try:

            base_dir = (
                self._resolve_secure_path(root_dir)
                if root_dir
                else self.workspace_path
            )

            matches = []

            iterator = (
                base_dir.rglob("*")
                if recursive
                else base_dir.glob("*")
            )

            for path in iterator:

                if not path.is_file():
                    continue

                filename = path.name.lower()

                # ============================================
                # MATCH
                # ============================================

                if (
                    pattern.lower() in filename
                    or fnmatch.fnmatch(
                        filename,
                        pattern.lower()
                    )
                ):

                    # ========================================
                    # EXTENSION FILTER
                    # ========================================

                    if extensions:

                        if (
                            path.suffix.lower()
                            not in extensions
                        ):
                            continue

                    matches.append({
                        "name": path.name,
                        "path": str(path),
                        "relative_path": str(path.relative_to(self.workspace_path)),
                        "size": path.stat().st_size,
                        "extension": path.suffix
                    })

            return {
                "success": True,
                "results": matches,
                "count": len(matches)
            }

        except Exception as e:

            logger.exception(
                "Error search_by_name"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # BUSCAR POR EXTENSION
    # ========================================================

    def search_by_extension(
        self,
        extension: str,
        root_dir: Optional[str] = None,
        recursive: bool = True
    ) -> Dict[str, Any]:
        """
        Busca archivos por extension dentro del workspace.
        """

        ext = extension.strip().lower()
        if ext and not ext.startswith("."):
            ext = f".{ext}"

        return self.search_by_name(
            pattern="*",
            root_dir=root_dir,
            extensions=[ext] if ext else None,
            recursive=recursive
        )

    # ========================================================
    # BUSCAR CONTENIDO
    # ========================================================

    def search_in_files(
        self,
        query: str,
        root_dir: Optional[str] = None,
        allowed_extensions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Busca texto dentro de archivos.

        Similar a grep local seguro.

        Args:
            query:
                Texto a buscar.

            root_dir:
                Directorio raíz.

            allowed_extensions:
                Extensiones permitidas.
        """

        try:

            base_dir = (
                self._resolve_secure_path(root_dir)
                if root_dir
                else self.workspace_path
            )

            if allowed_extensions is None:

                allowed_extensions = [
                    ".txt",
                    ".py",
                    ".json",
                    ".md",
                    ".csv",
                    ".log"
                ]

            results = []

            for file_path in base_dir.rglob("*"):

                if not file_path.is_file():
                    continue

                if (
                    file_path.suffix.lower()
                    not in allowed_extensions
                ):
                    continue

                try:

                    content = file_path.read_text(
                        encoding="utf-8",
                        errors="ignore"
                    )

                    if query.lower() in content.lower():

                        lines = []

                        for idx, line in enumerate(
                            content.splitlines(),
                            start=1
                        ):

                            if (
                                query.lower()
                                in line.lower()
                            ):

                                lines.append({
                                    "line_number": idx,
                                    "content": line.strip()
                                })

                        results.append({
                            "file": str(file_path),
                            "matches": lines
                        })

                except Exception:
                    continue

            return {
                "success": True,
                "results": results,
                "count": len(results)
            }

        except Exception as e:

            logger.exception(
                "Error search_in_files"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # BÚSQUEDA SEMÁNTICA
    # ========================================================

    def semantic_search(
        self,
        query: str,
        root_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Búsqueda heurística semántica.

        FUTURO:
        - embeddings
        - vector db
        - Gemini embeddings
        - local LLM

        Actualmente:
        - matching heurístico
        - sinónimos simples
        """

        try:

            base_dir = (
                self._resolve_secure_path(root_dir)
                if root_dir
                else self.workspace_path
            )

            # ====================================================
            # SINÓNIMOS BÁSICOS
            # ====================================================

            synonyms = {
                "foto": [
                    "imagen",
                    "picture",
                    "photo",
                    "jpg",
                    "png"
                ],
                "excel": [
                    "xlsx",
                    "xls",
                    "csv"
                ],
                "documento": [
                    "pdf",
                    "docx",
                    "txt"
                ],
                "cara": [
                    "rostro",
                    "face",
                    "persona"
                ]
            }

            query_words = query.lower().split()

            expanded_terms = set(query_words)

            for word in query_words:

                if word in synonyms:

                    expanded_terms.update(
                        synonyms[word]
                    )

            results = []

            for path in base_dir.rglob("*"):

                score = 0

                filename = path.name.lower()

                for term in expanded_terms:

                    if term in filename:
                        score += 1

                if score > 0:

                    results.append({
                        "path": str(path),
                        "name": path.name,
                        "score": score
                    })

            results.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            return {
                "success": True,
                "query": query,
                "results": results[:50]
            }

        except Exception as e:

            logger.exception(
                "Error semantic_search"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # DUPLICADOS
    # ========================================================

    def find_duplicates(
        self,
        root_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Encuentra archivos duplicados
        usando SHA256 binario.
        """

        try:

            base_dir = (
                self._resolve_secure_path(root_dir)
                if root_dir
                else self.workspace_path
            )

            hashes = {}

            duplicates = []

            for file_path in base_dir.rglob("*"):

                if not file_path.is_file():
                    continue

                try:

                    file_hash = self._hash_file(
                        file_path
                    )

                    if file_hash in hashes:

                        duplicates.append({
                            "original": hashes[file_hash],
                            "duplicate": str(file_path)
                        })

                    else:

                        hashes[file_hash] = str(file_path)

                except Exception:
                    continue

            return {
                "success": True,
                "duplicates": duplicates,
                "count": len(duplicates)
            }

        except Exception as e:

            logger.exception(
                "Error find_duplicates"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # HASH
    # ========================================================

    def _hash_file(
        self,
        path: Path
    ) -> str:
        """
        Calcula SHA256.
        """

        sha256 = hashlib.sha256()

        with open(path, "rb") as file:

            while True:

                chunk = file.read(8192)

                if not chunk:
                    break

                sha256.update(chunk)

        return sha256.hexdigest()

    # ========================================================
    # INDEXAR WORKSPACE
    # ========================================================

    def index_workspace(
        self
    ) -> Dict[str, Any]:
        """
        Genera índice completo del workspace.
        """

        try:

            files = []

            total_size = 0

            for path in self.workspace_path.rglob("*"):

                try:

                    info = {
                        "name": path.name,
                        "path": str(path),
                        "is_dir": path.is_dir(),
                        "extension": path.suffix
                    }

                    if path.is_file():

                        size = path.stat().st_size

                        info["size"] = size

                        total_size += size

                    files.append(info)

                except Exception:
                    continue

            return {
                "success": True,
                "workspace": str(
                    self.workspace_path
                ),
                "files_indexed": len(files),
                "total_size": total_size,
                "data": files
            }

        except Exception as e:

            logger.exception(
                "Error index_workspace"
            )

            return {
                "success": False,
                "error": str(e)
            }

