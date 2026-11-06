"""
======================================================================
MÓDULO: WORKSPACE CAPABILITIES — FaceSync AI Tools
Archivo: tools/workspace_tools.py
======================================================================
Responsabilidad:
- Ofrecer a la IA una comprensión profunda del workspace del usuario.
- Analizar telemetría, tamaños, extensiones y salud del entorno de trabajo.
- Detectar archivos duplicados por coincidencia exacta de HASH binario.
- Monitorear integridad del sandbox y cambios recientes.
======================================================================
"""

import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
from core.security import SecurityManager
from core.workspace_manager import WorkspaceManager

logger = logging.getLogger("FaceSync.WorkspaceTools")


class WorkspaceCapabilities:
    """
    Capacidades avanzadas de telemetría y diagnóstico del espacio de trabajo FaceSync.
    Proporciona al agente IA herramientas analíticas del sistema de archivos.
    """

    def __init__(self, workspace_path: str, security_manager: Optional[SecurityManager] = None):
        """
        Inicializa las capacidades de workspace.

        Args:
            workspace_path (str): Ruta base del espacio de trabajo.
            security_manager (Optional[SecurityManager]): Instancia de seguridad.
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.security = security_manager or SecurityManager(workspace_path=str(self.workspace_path))
        if Path(getattr(self.security, "workspace_path", self.workspace_path)).resolve() != self.workspace_path:
            self.security = SecurityManager(
                workspace_path=str(self.workspace_path),
                app_data_root=getattr(self.security, "app_data_path", None),
            )
        self.manager = WorkspaceManager(
            workspace_path=str(self.workspace_path),
            app_data_root=getattr(self.security, "app_data_path", None),
        )

    def set_project_root(self, project_root: str):
        self.workspace_path = Path(project_root).resolve()
        if hasattr(self.security, "set_project_root"):
            self.security.set_project_root(str(self.workspace_path))
        else:
            self.security = SecurityManager(workspace_path=str(self.workspace_path))
        self.manager.set_project_root(str(self.workspace_path))
        if hasattr(self.manager, "set_app_data_root"):
            self.manager.set_app_data_root(getattr(self.security, "app_data_path", None))

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    def _verify_and_resolve(self, path: str) -> Path:
        """
        Resuelve una ruta de forma segura garantizando el aislamiento del sandbox.
        """
        secure_path = self.security.secure_path(str(path))
        if not secure_path:
            raise PermissionError(f"Ruta fuera del sandbox: '{path}'")
        return Path(secure_path)

    def scan_workspace(self) -> Dict[str, Any]:
        """
        Escanea recursivamente el espacio de trabajo activo, devolviendo estructura limpia.

        Returns:
            Dict[str, Any]: Resultados estructurados del escaneo.
        """
        try:
            # Reutiliza el core del WorkspaceManager existente para consistencia
            return self.manager.scan_workspace()
        except Exception as e:
            logger.error(f"Error escaneando workspace: {e}")
            return {"success": False, "error": str(e)}

    def get_workspace_tree(self) -> str:
        """
        Retorna una representación visual en árbol jerárquico del workspace.

        Returns:
            str: Árbol formateado.
        """
        try:
            return self.manager.generate_tree()
        except Exception as e:
            logger.error(f"Error generando árbol: {e}")
            return f"Error al renderizar el árbol del workspace: {str(e)}"

    def get_workspace_metrics(self) -> Dict[str, Any]:
        """
        Calcula telemetría avanzada del workspace: tamaños totales, densidad de formatos y ocupación.

        Returns:
            Dict[str, Any]: Métricas calculadas.
        """
        metrics = {
            "total_size_mb": 0.0,
            "total_files": 0,
            "total_folders": 0,
            "largest_file": None,
            "extension_metrics": {}
        }
        try:
            scan = self.scan_workspace()
            metrics["total_files"] = scan.get("total_files", 0)
            metrics["total_folders"] = scan.get("total_folders", 0)

            total_bytes = 0
            largest_size = -1
            largest_info = None

            for file in scan.get("files", []):
                size = file.get("size_bytes", 0)
                total_bytes += size
                
                # Ocupación por extensión
                ext = file.get("extension", "").lower() or "sin_extension"
                if ext not in metrics["extension_metrics"]:
                    metrics["extension_metrics"][ext] = {"count": 0, "size_mb": 0.0}
                metrics["extension_metrics"][ext]["count"] += 1
                metrics["extension_metrics"][ext]["size_mb"] = round(
                    metrics["extension_metrics"][ext]["size_mb"] + (size / (1024 * 1024)), 4
                )

                if size > largest_size:
                    largest_size = size
                    largest_info = {
                        "name": file.get("name"),
                        "relative_path": file.get("relative_path"),
                        "size_mb": file.get("size_mb")
                    }

            metrics["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)
            metrics["largest_file"] = largest_info

        except Exception as e:
            logger.error(f"Error calculando métricas: {e}")
            metrics["error"] = str(e)

        return metrics

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verifica la salud y la integridad del workspace y del sandbox de seguridad.
        Comprueba que no se violen las directivas de seguridad ni falten componentes del core.

        Returns:
            Dict[str, Any]: Reporte de integridad.
        """
        report = {
            "workspace_exists": False,
            "sandbox_isolated": True,
            "critical_folders_check": {},
            "illegal_paths_found": [],
            "overall_integrity": "EXCELENTE"
        }
        try:
            # 1. Verificar existencia del workspace
            report["workspace_exists"] = self.manager.workspace_exists()
            if not report["workspace_exists"]:
                report["overall_integrity"] = "FALLIDA"
                return report

            # 2. Verificar carpetas críticas indispensables
            app_data_root = Path(getattr(self.security, "app_data_path", ""))
            criticals = ["sessions", "logs", "cache", "context", "temp"]
            for folder in criticals:
                path = app_data_root / folder
                exists = path.exists() and path.is_dir()
                report["critical_folders_check"][f"app_data/{folder}"] = "OK" if exists else "FALTANTE"
                if not exists:
                    report["overall_integrity"] = "DEGRADADA"

            # 3. Comprobación de fuga de sandbox (Simulada para test)
            escape_path = str(self.workspace_path / "../../")
            is_secure = self.security.validate_workspace_access(escape_path)
            if is_secure: # Si permite el acceso fuera, hay falla en sandbox
                report["sandbox_isolated"] = False
                report["overall_integrity"] = "CRÍTICA"

        except Exception as e:
            logger.error(f"Error verificando integridad: {e}")
            report["error"] = str(e)
            report["overall_integrity"] = "ERROR"

        return report

    def detect_duplicates(self) -> List[Dict[str, Any]]:
        """
        Escanea el workspace y agrupa los archivos duplicados basándose en coincidencia exacta de HASH SHA256.

        Returns:
            List[Dict[str, Any]]: Grupos de archivos duplicados.
        """
        duplicates_report = []
        try:
            scan = self.scan_workspace()
            hashes: Dict[str, List[Dict[str, Any]]] = {}

            # Agrupar archivos por su hash sha256
            for file in scan.get("files", []):
                file_path = file.get("path")
                if not file_path or not os.path.exists(file_path):
                    continue

                file_hash = self.manager.get_file_hash(file_path)
                if not file_hash:
                    continue

                info = {
                    "name": file.get("name"),
                    "relative_path": file.get("relative_path"),
                    "size_mb": file.get("size_mb")
                }

                if file_hash not in hashes:
                    hashes[file_hash] = []
                hashes[file_hash].append(info)

            # Filtrar solo aquellos hashes que tengan más de una coincidencia
            for file_hash, occurrences in hashes.items():
                if len(occurrences) > 1:
                    duplicates_report.append({
                        "hash_sha256": file_hash,
                        "size_mb": occurrences[0]["size_mb"],
                        "files": occurrences
                    })

        except Exception as e:
            logger.error(f"Error detectando duplicados: {e}")

        return duplicates_report

    def get_recent_changes(self, minutes: int = 1440) -> List[Dict[str, Any]]:
        """
        Retorna la lista de archivos creados o modificados en las últimas N horas.

        Args:
            minutes (int): Límite de tiempo en minutos (default: 24 horas).

        Returns:
            List[Dict[str, Any]]: Archivos con cambios recientes.
        """
        recent = []
        try:
            scan = self.scan_workspace()
            current_time = time.time()
            limit_seconds = minutes * 60

            for file in scan.get("files", []):
                file_path = file.get("path")
                if not file_path or not os.path.exists(file_path):
                    continue
                
                mtime = os.path.getmtime(file_path)
                elapsed = current_time - mtime
                
                if elapsed <= limit_seconds:
                    info = file.copy()
                    info["seconds_ago"] = int(elapsed)
                    info["formatted_elapsed"] = f"{int(elapsed // 60)} min" if elapsed >= 60 else "Menos de un minuto"
                    recent.append(info)

            # Ordenar por el cambio más reciente primero
            recent.sort(key=lambda x: x["seconds_ago"])

        except Exception as e:
            logger.error(f"Error consultando cambios recientes: {e}")

        return recent
