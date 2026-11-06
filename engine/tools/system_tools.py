
"""
======================================================================
MÓDULO: SYSTEM CAPABILITIES — FaceSync AI Tools
Archivo: tools/system_tools.py
======================================================================

Responsabilidad:
- Telemetría del sistema.
- Gestión segura de logs.
- Comandos controlados.
- Información del entorno.
- Limpieza de caché.
- Monitoreo de recursos.

Capacidades:
✔ Estado del sistema
✔ Información hardware/software
✔ Lectura segura de logs
✔ Ejecución de comandos whitelist
✔ Limpieza de caché
✔ Estadísticas del entorno
✔ Preparado para agentes IA

IMPORTANTE:
Este módulo JAMÁS debe permitir:
❌ comandos arbitrarios
❌ powershell libre
❌ cmd libre
❌ shell injection
❌ acceso fuera del workspace

======================================================================
"""

from __future__ import annotations

import os
import sys
import time
import json
import shutil
import logging
import platform
import subprocess

from pathlib import Path
from typing import Optional, Dict, List, Any

from core.security import SecurityManager

# ============================================================
# IMPORTS OPCIONALES
# ============================================================

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("FaceSync.SystemTools")

# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SystemCapabilities:
    """
    Sistema de capacidades del entorno.

    Diseñado para:
    - Agentes IA
    - Diagnósticos
    - Monitoreo
    - Telemetría
    - Gestión segura

    Seguridad:
    ✔ Sandbox
    ✔ Command whitelist
    ✔ Protección shell
    ✔ Sin ejecución arbitraria
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
        Inicializa SystemCapabilities.
        """

        self.workspace_path = Path(
            workspace_path
        ).resolve()

        self.security = (
            security_manager
            or SecurityManager(
                workspace_path=str(
                    self.workspace_path
                )
            )
        )

        # ====================================================
        # COMANDOS PERMITIDOS
        # ====================================================

        self.allowed_commands = {
            "python_version": [
                sys.executable,
                "--version"
            ],

            "pip_version": [
                "pip",
                "--version"
            ],

            "list_workspace": [
                "dir" if os.name == "nt" else "ls"
            ],

            "current_directory": [
                "cd"
            ],

            "environment": [
                "set" if os.name == "nt" else "env"
            ]
        }

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
            path
        )

        if not secure_path:
            raise PermissionError(
                f"Ruta insegura: {path}"
            )

        return Path(secure_path)

    # ========================================================
    # ESTADO SISTEMA
    # ========================================================

    def get_system_status(
        self
    ) -> Dict[str, Any]:
        """
        Obtiene estado general del sistema.
        """

        try:

            data = {
                "success": True,
                "platform": platform.system(),
                "platform_version": platform.version(),
                "python_version": platform.python_version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "workspace": str(
                    self.workspace_path
                ),
                "time": time.time()
            }

            # ====================================================
            # PSUTIL
            # ====================================================

            if PSUTIL_AVAILABLE:

                data["cpu_percent"] = (
                    psutil.cpu_percent()
                )

                memory = psutil.virtual_memory()

                data["memory"] = {
                    "total": memory.total,
                    "used": memory.used,
                    "percent": memory.percent
                }

                disk = psutil.disk_usage("/")

                data["disk"] = {
                    "total": disk.total,
                    "used": disk.used,
                    "percent": disk.percent
                }

            return data

        except Exception as e:

            logger.exception(
                "Error get_system_status"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # LOGS
    # ========================================================

    def get_system_logs(
        self,
        lines: int = 50,
        log_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Lee logs del sistema.

        Args:
            lines:
                Líneas finales.

            log_file:
                Archivo específico.
        """

        try:

            logs_dir = (
                self.workspace_path / "logs"
            )

            if not logs_dir.exists():

                return {
                    "success": False,
                    "error": (
                        "No existe carpeta logs."
                    )
                }

            # ================================================
            # LOG FILE
            # ================================================

            if log_file:

                target = self._resolve_secure_path(
                    str(logs_dir / log_file)
                )

            else:

                log_files = list(
                    logs_dir.glob("*.log")
                )

                if not log_files:

                    return {
                        "success": False,
                        "error": (
                            "No se encontraron logs."
                        )
                    }

                target = max(
                    log_files,
                    key=lambda f: f.stat().st_mtime
                )

            # ================================================
            # LEER
            # ================================================

            content = target.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            log_lines = content.splitlines()

            return {
                "success": True,
                "log_file": str(target),
                "lines": log_lines[-lines:]
            }

        except Exception as e:

            logger.exception(
                "Error get_system_logs"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # EJECUTAR COMANDO
    # ========================================================

    def execute_safe_command(
        self,
        command_name: str
    ) -> Dict[str, Any]:
        """
        Ejecuta comandos whitelist seguros.

        IMPORTANTE:
        Nunca ejecuta texto arbitrario.
        """

        try:

            if command_name not in self.allowed_commands:

                return {
                    "success": False,
                    "error": (
                        "Comando no permitido."
                    )
                }

            command = self.allowed_commands[
                command_name
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                shell=False,
                cwd=str(self.workspace_path)
            )

            return {
                "success": True,
                "command": command_name,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }

        except Exception as e:

            logger.exception(
                "Error execute_safe_command"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # LIMPIAR CACHE
    # ========================================================

    def clear_cache(
        self
    ) -> Dict[str, Any]:
        """
        Limpia cachés internas seguras.
        """

        try:

            cache_dir = (
                self.workspace_path / "cache"
            )

            if not cache_dir.exists():

                return {
                    "success": True,
                    "message": (
                        "No existe caché."
                    )
                }

            deleted = 0

            for item in cache_dir.iterdir():

                try:

                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

                    deleted += 1

                except Exception:
                    continue

            return {
                "success": True,
                "deleted_items": deleted
            }

        except Exception as e:

            logger.exception(
                "Error clear_cache"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # VARIABLES ENTORNO
    # ========================================================

    def get_environment_info(
        self
    ) -> Dict[str, Any]:
        """
        Obtiene información segura del entorno.
        """

        try:

            safe_env = {}

            allowed_keys = [
                "USERNAME",
                "USER",
                "OS",
                "COMPUTERNAME",
                "PROCESSOR_IDENTIFIER",
                "PYTHONPATH"
            ]

            for key in allowed_keys:

                if key in os.environ:

                    safe_env[key] = os.environ[key]

            return {
                "success": True,
                "environment": safe_env
            }

        except Exception as e:

            logger.exception(
                "Error get_environment_info"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # TAMAÑO WORKSPACE
    # ========================================================

    def get_workspace_size(
        self
    ) -> Dict[str, Any]:
        """
        Calcula tamaño del workspace.
        """

        try:

            total_size = 0
            total_files = 0

            for path in self.workspace_path.rglob("*"):

                try:

                    if path.is_file():

                        total_files += 1

                        total_size += (
                            path.stat().st_size
                        )

                except Exception:
                    continue

            return {
                "success": True,
                "workspace": str(
                    self.workspace_path
                ),
                "total_files": total_files,
                "total_size_bytes": total_size,
                "total_size_mb": round(
                    total_size / (1024 * 1024),
                    2
                )
            }

        except Exception as e:

            logger.exception(
                "Error get_workspace_size"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # INFO PYTHON
    # ========================================================

    def get_python_packages(
        self
    ) -> Dict[str, Any]:
        """
        Obtiene paquetes instalados.
        """

        try:

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "list",
                    "--format=json"
                ],
                capture_output=True,
                text=True,
                shell=False
            )

            packages = json.loads(
                result.stdout
            )

            return {
                "success": True,
                "packages_count": len(packages),
                "packages": packages
            }

        except Exception as e:

            logger.exception(
                "Error get_python_packages"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # DIAGNÓSTICO COMPLETO
    # ========================================================

    def full_diagnostic(
        self
    ) -> Dict[str, Any]:
        """
        Diagnóstico completo del sistema.
        """

        return {
            "success": True,
            "system": self.get_system_status(),
            "workspace": self.get_workspace_size(),
            "environment": self.get_environment_info(),
            "requirements": {
                "psutil": PSUTIL_AVAILABLE
            }
        }

