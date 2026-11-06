
"""
======================================================================
MÓDULO: WORKSPACE MANAGER — FaceSync AI
Archivo: core/workspace_manager.py
======================================================================

Responsabilidad:
- Gestionar TODO el workspace
- Escanear archivos y carpetas
- Crear mapas del sistema
- Obtener metadata
- Buscar archivos
- Leer estructura del proyecto
- Monitorear cambios
- Mantener contexto del explorador

Este módulo es los "ojos" del agente.

NO ejecuta IA.
NO modifica archivos.
SOLO analiza el workspace.

======================================================================
"""

import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.app_paths import ensure_app_data_root as ensure_app_data_root_path
from core.app_paths import filter_internal_names, path_is_inside


class WorkspaceManager:
    """
    Administrador profesional del workspace.
    """

    FACESYNC_WORKSPACE_NAME = "FaceSync_Workspace"

    # ==========================================================
    # INIT
    # ==========================================================

    def __init__(self, workspace_path: str, app_data_root: Optional[str] = None):

        self.workspace_path = os.path.abspath(workspace_path)
        self.project_root = self.workspace_path
        self.app_data_root = str(ensure_app_data_root_path(app_data_root))
        self.facesync_workspace = self.app_data_root
        self.active_path = self.project_root

        self.ignored_folders = [
            "__pycache__",
            self.FACESYNC_WORKSPACE_NAME,
            ".git",
            "env",
            "venv",
            "env_ia",
            "node_modules",
            ".idea",
            ".vscode"
        ]

        self.ignored_files = [
            ".DS_Store"
        ]

        self.supported_extensions = [
            ".txt",
            ".py",
            ".json",
            ".pdf",
            ".docx",
            ".xlsx",
            ".csv",
            ".jpg",
            ".jpeg",
            ".png",
            ".md"
        ]

    # ==========================================================
    # VALIDAR WORKSPACE
    # ==========================================================

    def workspace_exists(self) -> bool:
        """
        Verifica que exista el workspace.
        """

        return os.path.exists(self.workspace_path)

    def set_project_root(self, project_root: str):
        self.workspace_path = os.path.abspath(project_root)
        self.project_root = self.workspace_path
        if not path_is_inside(self.project_root, self.active_path):
            self.active_path = self.project_root

    def get_project_root(self) -> str:
        return self.project_root

    def set_app_data_root(self, app_data_root: Optional[str] = None) -> str:
        self.app_data_root = str(ensure_app_data_root_path(app_data_root))
        self.facesync_workspace = self.app_data_root
        return self.app_data_root

    def get_app_data_root(self) -> str:
        return self.app_data_root

    def ensure_app_data_root(self) -> str:
        return self.set_app_data_root(self.app_data_root)

    def set_active_path(self, active_path: str):
        if not active_path:
            return
        resolved = os.path.abspath(active_path)
        if path_is_inside(self.project_root, resolved):
            self.active_path = resolved

    def get_active_path(self) -> str:
        return self.active_path

    def get_facesync_workspace(self) -> str:
        return self.get_app_data_root()

    def ensure_facesync_workspace(self) -> str:
        return self.ensure_app_data_root()

    def resolve_client_path(self, path: str) -> str:
        value = str(path or "").strip()
        if not value:
            return self.project_root
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.project_root) / value
        candidate = candidate.resolve(strict=False)
        if not path_is_inside(self.project_root, candidate):
            raise PermissionError(f"Ruta fuera del project_root: {path}")
        return str(candidate)

    def resolve_internal_path(self, path: str) -> str:
        value = str(path or "").strip()
        if not value:
            return self.app_data_root
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.app_data_root) / value
        candidate = candidate.resolve(strict=False)
        if not path_is_inside(self.app_data_root, candidate):
            raise PermissionError(f"Ruta fuera de app_data_root: {path}")
        return str(candidate)

    # ==========================================================
    # ESCANEO GENERAL
    # ==========================================================

    def scan_workspace(self) -> Dict:
        """
        Escanea TODO el workspace.
        """

        result = {
            "workspace": self.workspace_path,
            "folders": [],
            "files": [],
            "total_files": 0,
            "total_folders": 0,
            "scan_time": datetime.now().isoformat()
        }

        if not self.workspace_exists():
            return result

        for root, dirs, files in os.walk(self.workspace_path):

            # ignorar carpetas
            dirs[:] = filter_internal_names([
                d for d in dirs
                if d not in self.ignored_folders
            ])

            # carpetas
            for folder in dirs:

                folder_path = os.path.join(root, folder)

                result["folders"].append({
                    "name": folder,
                    "path": folder_path,
                    "relative_path": os.path.relpath(
                        folder_path,
                        self.workspace_path
                    )
                })

            # archivos
            for file in files:

                if file in self.ignored_files:
                    continue

                file_path = os.path.join(root, file)

                result["files"].append(
                    self.get_file_info(file_path)
                )

        result["total_files"] = len(result["files"])
        result["total_folders"] = len(result["folders"])

        return result

    # ==========================================================
    # MAPA VISUAL
    # ==========================================================

    def generate_tree(self) -> str:
        """
        Genera árbol visual del proyecto.
        """

        lines = []

        root_name = os.path.basename(self.workspace_path)

        lines.append(f"📂 {root_name}/")

        for root, dirs, files in os.walk(self.workspace_path):

            dirs[:] = filter_internal_names([
                d for d in dirs
                if d not in self.ignored_folders
            ])

            level = root.replace(
                self.workspace_path,
                ""
            ).count(os.sep)

            indent = "│   " * level

            if root != self.workspace_path:
                lines.append(
                    f"{indent}📁 {os.path.basename(root)}/"
                )

            sub_indent = "│   " * (level + 1)

            for file in sorted(files):

                if file in self.ignored_files:
                    continue

                lines.append(
                    f"{sub_indent}📄 {file}"
                )

        return "\n".join(lines)

    # ==========================================================
    # INFO ARCHIVO
    # ==========================================================

    def get_file_info(
        self,
        file_path: str
    ) -> Dict:
        """
        Metadata completa de archivo.
        """

        try:

            stat = os.stat(file_path)

            return {
                "name": os.path.basename(file_path),
                "path": file_path,
                "relative_path": os.path.relpath(
                    file_path,
                    self.workspace_path
                ),
                "extension": os.path.splitext(file_path)[1],
                "size_bytes": stat.st_size,
                "size_mb": round(
                    stat.st_size / (1024 * 1024),
                    4
                ),
                "modified": datetime.fromtimestamp(
                    stat.st_mtime
                ).isoformat(),
                "created": datetime.fromtimestamp(
                    stat.st_ctime
                ).isoformat()
            }

        except Exception as e:

            return {
                "error": str(e),
                "path": file_path
            }

    # ==========================================================
    # BUSCAR ARCHIVOS
    # ==========================================================

    def search_files(
        self,
        query: str
    ) -> List[Dict]:
        """
        Busca archivos por nombre.
        """

        query = query.lower()

        results = []

        scan = self.scan_workspace()

        for file in scan["files"]:

            name = file.get("name", "").lower()

            if query in name:
                results.append(file)

        return results

    # ==========================================================
    # BUSCAR POR EXTENSIÓN
    # ==========================================================

    def get_files_by_extension(
        self,
        extension: str
    ) -> List[Dict]:
        """
        Obtiene archivos por extensión.
        """

        results = []

        scan = self.scan_workspace()

        for file in scan["files"]:

            ext = file.get("extension", "").lower()

            if ext == extension.lower():
                results.append(file)

        return results

    # ==========================================================
    # OBTENER CONTENIDO CARPETA
    # ==========================================================

    def list_directory(
        self,
        relative_path: str = ""
    ) -> Dict:
        """
        Lista contenido de carpeta.
        """

        target = os.path.join(
            self.workspace_path,
            relative_path
        )

        if not os.path.exists(target):

            return {
                "success": False,
                "error": "Carpeta no existe"
            }

        folders = []
        files = []

        try:

            for item in os.listdir(target):

                full_path = os.path.join(
                    target,
                    item
                )

                if os.path.isdir(full_path):

                    if item not in self.ignored_folders:
                        folders.append(item)

                else:

                    if item not in self.ignored_files:
                        files.append(item)

            return {
                "success": True,
                "path": target,
                "folders": sorted(folders),
                "files": sorted(files)
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e)
            }

    # ==========================================================
    # HASH ARCHIVO
    # ==========================================================

    def get_file_hash(
        self,
        file_path: str
    ) -> Optional[str]:
        """
        Hash SHA256 de archivo.
        """

        try:

            sha256 = hashlib.sha256()

            with open(file_path, "rb") as f:

                while True:

                    chunk = f.read(4096)

                    if not chunk:
                        break

                    sha256.update(chunk)

            return sha256.hexdigest()

        except Exception:
            return None

    # ==========================================================
    # DETECTAR CAMBIOS
    # ==========================================================

    def snapshot_workspace(self) -> Dict:
        """
        Snapshot del estado actual.
        """

        snapshot = {}

        scan = self.scan_workspace()

        for file in scan["files"]:

            path = file["path"]

            snapshot[path] = {
                "hash": self.get_file_hash(path),
                "modified": file["modified"]
            }

        return snapshot

    def compare_snapshots(
        self,
        old_snapshot: Dict,
        new_snapshot: Dict
    ) -> Dict:
        """
        Detecta cambios entre snapshots.
        """

        changes = {
            "added": [],
            "removed": [],
            "modified": []
        }

        old_files = set(old_snapshot.keys())
        new_files = set(new_snapshot.keys())

        # nuevos
        changes["added"] = list(
            new_files - old_files
        )

        # eliminados
        changes["removed"] = list(
            old_files - new_files
        )

        # modificados
        common = old_files.intersection(new_files)

        for file in common:

            old_hash = old_snapshot[file]["hash"]
            new_hash = new_snapshot[file]["hash"]

            if old_hash != new_hash:
                changes["modified"].append(file)

        return changes

    # ==========================================================
    # RESUMEN
    # ==========================================================

    def workspace_summary(self) -> Dict:
        """
        Resumen inteligente del proyecto.
        """

        scan = self.scan_workspace()

        extensions = {}

        for file in scan["files"]:

            ext = file.get("extension", "")

            if ext not in extensions:
                extensions[ext] = 0

            extensions[ext] += 1

        return {
            "workspace": self.workspace_path,
            "total_files": scan["total_files"],
            "total_folders": scan["total_folders"],
            "extensions": extensions
        }

    # ==========================================================
    # COMPATIBILIDAD CON AGENT CONTROLLER
    # ==========================================================

    def index_workspace(self) -> Dict:
        """
        Alias estructurado para controladores del agente.
        """

        return self.scan_workspace()

    def get_workspace_summary(self) -> Dict:
        """
        Alias legacy del resumen del workspace.
        """

        return self.workspace_summary()

    def get_workspace_tree(self) -> str:
        """
        Alias legacy del arbol visual.
        """

        return self.generate_tree()

    def create_folder(self, folder_name: str, target_path: str = "") -> str:
        """
        Crea una carpeta usando las capabilities seguras.
        """

        from tools.file_tools import FileCapabilities

        relative_path = os.path.join(target_path or "", folder_name or "")
        return FileCapabilities(self.workspace_path).create_directory(relative_path)

    def delete_resource(self, path: str, recursive: bool = True) -> str:
        """
        Elimina un recurso dentro del workspace.
        """

        from tools.file_tools import FileCapabilities

        return FileCapabilities(self.workspace_path).delete_path(path, recursive=recursive)

    def move_resource(self, source: str, destination: str) -> str:
        """
        Mueve un recurso dentro del workspace.
        """

        from tools.file_tools import FileCapabilities

        return FileCapabilities(self.workspace_path).move_path(source, destination)

    def read_document(self, path: str) -> Dict:
        """
        Lee un documento usando la capa documental segura.
        """

        from tools.document_tools import DocumentCapabilities

        return DocumentCapabilities(self.workspace_path).read_document(path)

    # ==========================================================
    # DEBUG
    # ==========================================================

    def debug_workspace(self):
        """
        Debug completo.
        """

        print("\n" + "=" * 60)
        print("WORKSPACE DEBUG")
        print("=" * 60)

        summary = self.workspace_summary()

        print(f"\nWorkspace:")
        print(summary["workspace"])

        print(f"\nTotal archivos:")
        print(summary["total_files"])

        print(f"\nTotal carpetas:")
        print(summary["total_folders"])

        print(f"\nExtensiones:")
        for ext, count in summary["extensions"].items():
            print(f"{ext}: {count}")

        print("\nÁRBOL:")
        print(self.generate_tree())

        print("=" * 60)


# ==============================================================
# TEST LOCAL
# ==============================================================

if __name__ == "__main__":

    workspace = WorkspaceManager(
        workspace_path="."
    )

    workspace.debug_workspace()

    print("\n")
    print("=" * 50)

    result = workspace.search_files("main")

    print("BÚSQUEDA:")
    print(result)
