"""
File capabilities for FaceSync AI.

All mutating operations validate paths through SecurityManager and return a
standard dict result. Legacy callers that stringify the result still get a
useful message inside the dict.
"""

from __future__ import annotations

import filecmp
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from core.security import SecurityManager
from core.safe_delete import send_to_recycle_bin
from core.tool_execution_gate import ToolExecutionGate
from tools.tool_result import tool_error, tool_result

logger = logging.getLogger("FaceSync.FileTools")


class FileCapabilities:
    def __init__(self, workspace_path: str, security_manager: Optional[SecurityManager] = None):
        self.workspace_path = Path(workspace_path).resolve()
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

    def _resolve_and_verify(self, target_path: str | Path, operation: str = "read") -> Path:
        secure_path = self.security.secure_path(str(target_path))
        if not secure_path:
            raise PermissionError(f"Acceso denegado: la ruta '{target_path}' sale del workspace.")
        if operation != "directory":
            is_valid, reason = self.security.validate_operation(operation, secure_path)
            if not is_valid:
                raise PermissionError(f"Acceso denegado por seguridad: {reason}")
        return Path(secure_path)

    def _relative_parts(self, target: Path) -> list[str]:
        try:
            relative = target.resolve(strict=False).relative_to(self.workspace_path)
        except ValueError:
            return []
        return [part for part in relative.parts if part not in ("", ".")]

    def _validate_folder_parts(self, target: Path, action: str) -> Dict[str, Any] | None:
        for part in self._relative_parts(target):
            is_valid, reason = self.security.validate_folder_name(part)
            if not is_valid:
                return tool_error(action, f"Error de seguridad: {reason}")
        return None

    def create_file(self, path: str, content: str = "", overwrite: bool = False) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("create_file", file_name=path)
            if not ok:
                return tool_error("create_file", reason)
            target = self._resolve_and_verify(path, operation="write")
            if target.exists() and not overwrite:
                current = target.read_text(encoding="utf-8", errors="replace")
                if current == content:
                    return tool_result(success=True, action="create_file", message="El archivo ya existía, se reutilizó.", reused=[path], skipped=[path])
                return tool_error("create_file", f"El archivo ya existe en '{path}' con contenido distinto.")
            error = self._validate_folder_parts(target.parent, "create_file")
            if error:
                return error
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return tool_result(success=True, action="create_file", message="Archivo creado correctamente.", created=[path])
        except Exception as exc:
            logger.error("Error creando archivo: %s", exc)
            return tool_error("create_file", f"Error al crear el archivo: {exc}")

    def create_directory(self, path: str) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("create_folder", folder_name=path)
            if not ok:
                return tool_error("create_folder", reason)
            target = self._resolve_and_verify(path, operation="directory")
            error = self._validate_folder_parts(target, "create_folder")
            if error:
                return error
            existed = target.exists()
            target.mkdir(parents=True, exist_ok=True)
            if existed:
                return tool_result(success=True, action="create_folder", message="La carpeta ya existía, se reutilizó.", reused=[path])
            return tool_result(success=True, action="create_folder", message="Carpeta creada correctamente.", created=[path])
        except Exception as exc:
            logger.error("Error creando carpeta: %s", exc)
            return tool_error("create_folder", f"Error al crear la carpeta: {exc}")

    def create_multiple_folders(self, quantity: int, base_name: str, destination_folder: str = "") -> Dict[str, Any]:
        created, reused, errors = [], [], []
        quantity = int(quantity or 0)
        width = max(2, len(str(quantity)))
        destination = str(destination_folder or "").strip().strip("/\\")
        for index in range(1, quantity + 1):
            folder_name = f"{base_name}_{index:0{width}d}" if quantity > 1 else str(base_name)
            path = f"{destination}/{folder_name}" if destination else folder_name
            result = self.create_directory(path)
            if result.get("success"):
                created.extend(result.get("created", []))
                reused.extend(result.get("reused", []))
            else:
                errors.extend(result.get("errors") or [result.get("message", "Error")])
        return tool_result(
            success=not errors,
            action="create_multiple_folders",
            message="Carpetas procesadas.",
            created=created,
            reused=reused,
            errors=errors,
            metadata={"created_count": len(created), "reused_count": len(reused), "requested_count": quantity},
        )

    def delete_path(self, path: str, recursive: bool = False) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("delete_item", target=path)
            if not ok:
                return tool_error("delete_item", reason)
            target = self._resolve_and_verify(path, operation="delete")
            is_safe, reason = self.security.validate_delete(str(target))
            if not is_safe:
                return tool_error("delete_item", f"Operación cancelada: {reason}")
            if target.resolve(strict=False) == self.workspace_path.resolve(strict=False):
                return tool_error("delete_item", "Operación cancelada: no se puede borrar la raíz del proyecto.")
            if not target.exists():
                return tool_error("delete_item", f"El elemento '{path}' no existe.")
            if target.is_dir() and not recursive and any(target.iterdir()):
                return tool_error("delete_item", f"La carpeta '{path}' no está vacía. Use recursive=True para confirmar el borrado.")
            send_to_recycle_bin(target)
            return tool_result(success=True, action="delete_item", message="Elemento eliminado correctamente.", deleted=[path])
        except Exception as exc:
            logger.error("Error eliminando elemento: %s", exc)
            return tool_error("delete_item", f"Error al eliminar el elemento: {exc}")

    def move_path(self, src: str, dest: str) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("move_item", target=src, destination_folder=dest)
            if not ok:
                return tool_error("move_item", reason)
            source = self._resolve_and_verify(src, operation="read")
            destination = self._resolve_and_verify(dest, operation="write")
            if not source.exists():
                return tool_error("move_item", f"El origen '{src}' no existe.")
            if destination.exists() and destination.is_dir():
                destination = destination / source.name
            if destination.exists():
                if self._same_entry(source, destination):
                    return tool_result(success=True, action="move_item", message="El destino ya existía idéntico, se reutilizó.", reused=[str(destination)], skipped=[src])
                return tool_error("move_item", f"El destino '{dest}' ya existe. Elija otro nombre o elimínelo primero.")
            error = self._validate_folder_parts(destination.parent, "move_item")
            if error:
                return error
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return tool_result(success=True, action="move_item", message="Elemento movido correctamente.", moved=[str(destination)])
        except Exception as exc:
            logger.error("Error moviendo elemento: %s", exc)
            return tool_error("move_item", f"Error al mover el elemento: {exc}")

    def rename_path(self, path: str, new_name: str) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("rename_item", target=path, new_name=new_name)
            if not ok:
                return tool_error("rename_item", reason)
            target = self._resolve_and_verify(path, operation="write")
            if "/" in new_name or "\\" in new_name:
                return tool_error("rename_item", "El nuevo nombre no debe contener separadores de ruta.")
            sanitized_name = self.security.sanitize_filename(new_name)
            if not target.exists():
                return tool_error("rename_item", f"El elemento '{path}' no existe.")
            new_path = self._resolve_and_verify(target.parent / sanitized_name, operation="write")
            if new_path.exists():
                if new_path.resolve(strict=False) == target.resolve(strict=False):
                    return tool_result(success=True, action="rename_item", message="El elemento ya tenía ese nombre.", reused=[path], skipped=[path])
                return tool_error("rename_item", f"Ya existe un elemento con el nombre '{sanitized_name}' en la misma ubicación.")
            target.rename(new_path)
            return tool_result(success=True, action="rename_item", message="Elemento renombrado correctamente.", moved=[str(new_path)])
        except Exception as exc:
            logger.error("Error renombrando elemento: %s", exc)
            return tool_error("rename_item", f"Error al renombrar el elemento: {exc}")

    def copy_path(self, src: str, dest: str) -> Dict[str, Any]:
        try:
            ok, reason = ToolExecutionGate.validate_tool_args("copy_item", target=src, destination_folder=dest)
            if not ok:
                return tool_error("copy_item", reason)
            source = self._resolve_and_verify(src, operation="read")
            destination = self._resolve_and_verify(dest, operation="write")
            if not source.exists():
                return tool_error("copy_item", f"El origen '{src}' no existe.")
            if destination.exists() and destination.is_dir():
                destination = destination / source.name
            if destination.exists():
                if self._same_entry(source, destination):
                    return tool_result(success=True, action="copy_item", message="El destino ya existía idéntico, se reutilizó.", reused=[dest], skipped=[src])
                return tool_error("copy_item", f"El destino '{dest}' ya existe.")
            error = self._validate_folder_parts(destination.parent, "copy_item")
            if error:
                return error
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination) if source.is_dir() else shutil.copy2(source, destination)
            return tool_result(success=True, action="copy_item", message="Elemento copiado correctamente.", copied=[str(destination)])
        except Exception as exc:
            logger.error("Error copiando elemento: %s", exc)
            return tool_error("copy_item", f"Error al copiar el elemento: {exc}")

    def _same_entry(self, source: Path, destination: Path) -> bool:
        if not source.exists() or not destination.exists() or source.is_dir() != destination.is_dir():
            return False
        if source.is_file():
            return source.stat().st_size == destination.stat().st_size and filecmp.cmp(source, destination, shallow=False)
        source_files = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
        dest_files = sorted(path.relative_to(destination) for path in destination.rglob("*") if path.is_file())
        return source_files == dest_files and all(filecmp.cmp(source / rel, destination / rel, shallow=False) for rel in source_files)

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        return self.create_file(path, content=content, overwrite=True)

    def append_file(self, path: str, content: str) -> Dict[str, Any]:
        try:
            target = self._resolve_and_verify(path, operation="write")
            if not target.exists():
                return tool_error("append_file", f"El archivo '{path}' no existe. Use write_file o create_file primero.")
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
            return tool_result(success=True, action="append_file", message="Texto añadido correctamente.", moved=[path])
        except Exception as exc:
            logger.error("Error agregando texto: %s", exc)
            return tool_error("append_file", f"Error al adjuntar contenido: {exc}")

    def read_file(self, path: str) -> str:
        try:
            target = self._resolve_and_verify(path, operation="read")
            is_valid, reason = self.security.validate_read_file(str(target))
            if not is_valid:
                return f"Error de seguridad al leer el archivo: {reason}"
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.error("Error leyendo archivo: %s", exc)
            return f"Error al leer el archivo: {exc}"
