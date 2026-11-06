
"""
======================================================================
MÓDULO: SECURITY — FaceSync AI
Archivo: core/security.py
======================================================================

Responsabilidad:
- Proteger el workspace
- Validar rutas
- Evitar path traversal
- Bloquear operaciones peligrosas
- Limitar acceso SOLO al workspace
- Validar extensiones
- Validar tamaño de archivos
- Sanitizar nombres

Este módulo es CRÍTICO.
TODO pasa por aquí antes de ejecutarse.

======================================================================
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from core.app_paths import ensure_app_data_root


class SecurityManager:
    """
    Gestor central de seguridad.
    """

    # ==========================================================
    # CONFIG
    # ==========================================================

    MAX_FILE_SIZE_MB = 100

    BLOCKED_EXTENSIONS = [
        ".exe",
        ".bat",
        ".cmd",
        ".msi",
        ".dll",
        ".sys",
        ".ps1",
        ".vbs",
        ".scr"
    ]

    ALLOWED_READ_EXTENSIONS = [
        ".txt",
        ".pdf",
        ".docx",
        ".xlsx",
        ".xls",
        ".csv",
        ".json",
        ".xml",
        ".py",
        ".md",
        ".jpg",
        ".jpeg",
        ".png"
    ]

    BLOCKED_FOLDERS = [
        "windows",
        "system32",
        "program files",
        "appdata",
        ".git",
        "__pycache__",
        "env",
        "venv",
        "env_ia"
    ]

    INVALID_CHARS = r'[<>:"/\\|?*]'

    # ==========================================================
    # INIT
    # ==========================================================

    def __init__(self, workspace_path: str, app_data_root: Optional[str] = None):
        if not workspace_path or not str(workspace_path).strip():
            raise ValueError("SecurityManager requiere un workspace_path valido.")

        self.set_project_root(workspace_path)
        self.set_app_data_root(app_data_root)

    def set_project_root(self, workspace_path: str):
        if not workspace_path or not str(workspace_path).strip():
            raise ValueError("SecurityManager requiere un workspace_path valido.")

        self.workspace_path = str(Path(workspace_path).expanduser().resolve(strict=False))
        self.workspace_root = Path(self.workspace_path)
        # Multi-root: por defecto una sola raiz permitida (compatibilidad).
        self.workspace_roots = [self.workspace_root]

    def set_workspace_roots(self, roots):
        """Define varias raices permitidas (workspace compuesto). La primera es
        la primaria (compatibilidad). Las rutas se validan contra cualquiera."""
        resolved = []
        for r in roots or []:
            if r and str(r).strip():
                p = Path(str(r)).expanduser().resolve(strict=False)
                if p not in resolved:
                    resolved.append(p)
        if not resolved:
            return
        self.workspace_path = str(resolved[0])
        self.workspace_root = resolved[0]
        self.workspace_roots = resolved

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    def set_app_data_root(self, app_data_root: Optional[str] = None):
        self.app_data_root = ensure_app_data_root(app_data_root)
        self.app_data_path = str(self.app_data_root)

    def get_app_data_root(self) -> str:
        return self.app_data_path

    @staticmethod
    def validate_workspace(workspace_path: str) -> bool:
        """
        Compatibilidad para controladores legacy: valida que exista un workspace.
        """

        if not workspace_path or not str(workspace_path).strip():
            raise ValueError("No hay workspace configurado.")

        path = Path(workspace_path).expanduser().resolve()

        if not path.exists() or not path.is_dir():
            raise ValueError(f"Workspace invalido o inexistente: {workspace_path}")

        return True

    @staticmethod
    def validate_path(path: str, workspace_path: str) -> str:
        """
        Compatibilidad legacy: resuelve una ruta dentro del workspace indicado.
        """

        security = SecurityManager(workspace_path)
        secure = security.secure_path(path)

        if not secure:
            raise PermissionError("Ruta fuera del workspace autorizado.")

        return secure

    # ==========================================================
    # VALIDAR RUTA SEGURA
    # ==========================================================

    def secure_path(
        self,
        user_path: str
    ) -> Optional[str]:
        """
        Convierte ruta relativa en absoluta segura.

        Bloquea:
        - ../
        - rutas externas
        - acceso fuera del workspace
        """

        return self.secure_client_path(user_path)

    def secure_client_path(self, user_path: str) -> Optional[str]:
        # Multi-root: aceptar si la ruta cae dentro de CUALQUIER raiz permitida.
        for root in getattr(self, "workspace_roots", None) or [self.workspace_root]:
            result = self._secure_path_in_root(root, user_path)
            if result is not None:
                return result
        return None

    def secure_internal_path(self, user_path: str) -> Optional[str]:
        return self._secure_path_in_root(self.app_data_root, user_path)

    def is_safe_client_path(self, user_path: str) -> bool:
        return self.secure_client_path(user_path) is not None

    def is_safe_internal_path(self, user_path: str) -> bool:
        return self.secure_internal_path(user_path) is not None

    def _secure_path_in_root(self, root: Path, user_path: str) -> Optional[str]:
        if user_path is None:
            return None

        try:
            root = Path(root).expanduser().resolve(strict=False)
            user_path = str(user_path).strip()

            if not user_path:
                return None

            user_path = user_path.replace('"', '')
            user_path = user_path.replace("'", "")

            if Path(user_path).is_absolute():
                candidate = Path(user_path).expanduser().resolve(strict=False)
                try:
                    candidate.relative_to(root)
                except ValueError:
                    return None
                return str(candidate)

            collapsed = re.sub(r"\s+", "", user_path)
            if re.match(r"^[A-Za-z]:?[\\/]", collapsed):
                candidate_drive = Path(collapsed).expanduser().resolve(strict=False)
                try:
                    candidate_drive.relative_to(root)
                except ValueError:
                    return None

            candidate = (root / user_path).resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError:
                return None

            return str(candidate)
        except Exception:
            return None

    # ==========================================================
    # VALIDAR ACCESO
    # ==========================================================

    def validate_workspace_access(
        self,
        path: str
    ) -> bool:
        """
        Verifica acceso válido al workspace.
        """

        secure = self.secure_path(path)

        return secure is not None

    # ==========================================================
    # DETECTAR PATH TRAVERSAL
    # ==========================================================

    def detect_path_traversal(
        self,
        path: str
    ) -> bool:
        """
        Detecta intentos de escape.
        """

        dangerous_patterns = [
            "../",
            "..\\",
            "/etc/",
            "c:\\windows",
            "system32",
            "~",
            "%appdata%"
        ]

        path_lower = path.lower()

        return any(
            pattern in path_lower
            for pattern in dangerous_patterns
        )

    # ==========================================================
    # VALIDAR EXTENSIÓN
    # ==========================================================

    def validate_extension(
        self,
        file_path: str,
        operation: str = "read"
    ) -> Tuple[bool, str]:
        """
        Valida extensión permitida.
        """

        ext = os.path.splitext(file_path)[1].lower()

        # bloqueadas
        if ext in self.BLOCKED_EXTENSIONS:
            return False, f"Extensión bloqueada: {ext}"

        # lectura
        if operation == "read":
            if ext not in self.ALLOWED_READ_EXTENSIONS:
                return False, f"Extensión no soportada: {ext}"

        return True, "OK"

    # ==========================================================
    # VALIDAR TAMAÑO
    # ==========================================================

    def validate_file_size(
        self,
        file_path: str
    ) -> Tuple[bool, str]:
        """
        Bloquea archivos demasiado grandes.
        """

        try:

            if not os.path.exists(file_path):
                return False, "Archivo no existe"

            size_mb = os.path.getsize(file_path) / (1024 * 1024)

            if size_mb > self.MAX_FILE_SIZE_MB:
                return False, (
                    f"Archivo demasiado grande "
                    f"({size_mb:.2f} MB)"
                )

            return True, "OK"

        except Exception as e:
            return False, str(e)

    # ==========================================================
    # VALIDAR NOMBRE
    # ==========================================================

    def sanitize_filename(
        self,
        filename: str
    ) -> str:
        """
        Limpia nombres peligrosos.
        """

        # quitar caracteres inválidos
        filename = re.sub(
            self.INVALID_CHARS,
            "",
            filename
        )

        # quitar espacios extremos
        filename = filename.strip()

        # evitar nombres vacíos
        if not filename:
            filename = "archivo"

        return filename

    # ==========================================================
    # VALIDAR CARPETA
    # ==========================================================

    def validate_folder_name(
        self,
        folder_name: str
    ) -> Tuple[bool, str]:
        """
        Bloquea carpetas peligrosas.
        """

        folder_lower = folder_name.strip().lower()

        for blocked in self.BLOCKED_FOLDERS:

            if blocked == folder_lower:
                return (
                    False,
                    f"Carpeta bloqueada: {blocked}"
                )

        return True, "OK"

    # ==========================================================
    # VALIDAR OPERACIÓN
    # ==========================================================

    def validate_operation(
        self,
        operation: str,
        target_path: str
    ) -> Tuple[bool, str]:
        """
        Validación completa.
        """

        # path traversal
        if self.detect_path_traversal(target_path):
            return (
                False,
                "Intento de path traversal detectado"
            )

        # acceso workspace
        secure = self.secure_path(target_path)

        if not secure:
            return (
                False,
                "Ruta fuera del workspace"
            )

        # extensiones
        valid_ext, msg = self.validate_extension(
            secure,
            operation="read"
        )

        # ignorar carpetas
        if os.path.splitext(secure)[1]:

            if not valid_ext:
                return False, msg

        return True, "OK"

    # ==========================================================
    # VALIDAR LECTURA
    # ==========================================================

    def validate_read_file(
        self,
        file_path: str
    ) -> Tuple[bool, str]:
        """
        Seguridad completa para lectura.
        """

        secure = self.secure_path(file_path)

        if not secure:
            return False, "Ruta inválida"

        if not os.path.exists(secure):
            return False, "Archivo no existe"

        ext_ok, ext_msg = self.validate_extension(
            secure,
            "read"
        )

        if not ext_ok:
            return False, ext_msg

        size_ok, size_msg = self.validate_file_size(
            secure
        )

        if not size_ok:
            return False, size_msg

        return True, "OK"

    # ==========================================================
    # VALIDAR ESCRITURA
    # ==========================================================

    def validate_write_file(
        self,
        file_path: str
    ) -> Tuple[bool, str]:
        """
        Seguridad completa para escritura.
        """

        secure = self.secure_path(file_path)

        if not secure:
            return False, "Ruta inválida"

        ext = os.path.splitext(secure)[1].lower()

        if ext in self.BLOCKED_EXTENSIONS:
            return False, "Extensión peligrosa"

        return True, "OK"

    # ==========================================================
    # VALIDAR BORRADO
    # ==========================================================

    def validate_delete(
        self,
        target_path: str
    ) -> Tuple[bool, str]:
        """
        Evita borrar cosas críticas.
        """

        secure = self.secure_path(target_path)

        if not secure:
            return False, "Ruta inválida"

        critical_paths = [
            self.workspace_path,
            os.path.join(self.workspace_path, "core"),
            os.path.join(self.workspace_path, "tools"),
            os.path.join(self.workspace_path, "ai")
        ]

        secure_lower = secure.lower()

        for critical in critical_paths:

            if secure_lower == critical.lower():
                return (
                    False,
                    "No puedes borrar carpetas críticas"
                )

        return True, "OK"

    # ==========================================================
    # REPORTE SEGURIDAD
    # ==========================================================

    def security_report(self) -> dict:
        """
        Estado del sistema.
        """

        return {
            "workspace": self.workspace_path,
            "project_root": self.workspace_path,
            "app_data_root": self.app_data_path,
            "max_file_size_mb": self.MAX_FILE_SIZE_MB,
            "blocked_extensions": self.BLOCKED_EXTENSIONS,
            "allowed_read_extensions": self.ALLOWED_READ_EXTENSIONS,
            "blocked_folders": self.BLOCKED_FOLDERS
        }

    # ==========================================================
    # DEBUG
    # ==========================================================

    def debug_security(
        self,
        path: str
    ):
        """
        Debug rápido.
        """

        print("\n" + "=" * 60)
        print("SECURITY DEBUG")
        print("=" * 60)

        print(f"\nRuta original:")
        print(path)

        print(f"\nRuta segura:")
        print(self.secure_path(path))

        print(f"\nPath traversal:")
        print(self.detect_path_traversal(path))

        print(f"\nWorkspace access:")
        print(self.validate_workspace_access(path))

        print("=" * 60)


# ==============================================================
# TEST LOCAL
# ==============================================================

if __name__ == "__main__":

    security = SecurityManager(
        workspace_path="C:/FaceSync"
    )

    tests = [
        "usuarios/test.txt",
        "../windows/system32",
        "ventas/reporte.pdf",
        "malware.exe"
    ]

    for test in tests:

        print("\n")
        print("=" * 50)

        secure = security.secure_path(test)

        print(f"Original: {test}")
        print(f"Seguro: {secure}")

        ok, msg = security.validate_read_file(test)

        print(f"Validación: {ok}")
        print(f"Mensaje: {msg}")
