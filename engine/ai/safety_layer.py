"""
======================================================================
MÓDULO: SAFETY LAYER — Capa de Seguridad Proactiva y Anti-Jailbreak
Archivo: ai/safety_layer.py
======================================================================
Responsabilidad:
- Analizar prompts de usuario para interceptar ataques de Jailbreak/Prompt Injection.
- Prevenir y bloquear solicitudes de ejecución destructiva masiva accidental.
- Validar argumentos de llamadas a herramientas (Tool Calling) en tiempo real.
- Bloquear intentos de escape del Sandbox de manera proactiva antes de invocar Python.
======================================================================
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from core.security import SecurityManager

logger = logging.getLogger("FaceSync.SafetyLayer")


class SafetyLayer:
    """
    Capa de protección proactiva e inquebrantable del agente FaceSync.
    Actúa como cortafuegos lógico entre el prompt humano, el LLM y el sistema operativo.
    """

    # Palabras clave sospechosas de Prompt Injection o evasión de sandbox
    DANGEROUS_PROMPT_KEYWORDS = [
        "ignore previous instructions",
        "ignora las instrucciones anteriores",
        "system prompt",
        "forget all rules",
        "olvida las reglas",
        "actúa como un modo libre",
        "jailbreak",
        "sudo rm",
        "format c:",
        "cmd.exe",
        "powershell.exe",
        "/etc/passwd"
    ]

    def __init__(self, workspace_path: str, security_manager: Optional[SecurityManager] = None):
        """
        Inicializa la capa de seguridad.

        Args:
            workspace_path (str): Ruta base del espacio de trabajo.
            security_manager (Optional[SecurityManager]): Instancia de seguridad central.
        """
        self.workspace_path = workspace_path
        self.security = security_manager or SecurityManager(workspace_path=self.workspace_path)

    def validate_user_prompt(self, prompt: str) -> Tuple[bool, str]:
        """
        Analiza el texto del usuario antes de enviarlo a Gemini para bloquear
        inyecciones maliciosas o solicitudes deliberadas de escape.

        Args:
            prompt (str): Mensaje natural del usuario.

        Returns:
            Tuple[bool, str]: (is_safe, reason_if_not_safe)
        """
        if not prompt:
            return True, "OK"

        prompt_lower = prompt.lower()

        # 1. Comprobar inyección de prompts
        for keyword in self.DANGEROUS_PROMPT_KEYWORDS:
            if keyword in prompt_lower:
                logger.warning(f"Seguridad: Prompt bloqueado por palabra clave peligrosa: '{keyword}'")
                return False, f"Petición cancelada: Se detectó terminología restringida de inyección de prompt o comando."

        # 2. Comprobar intentos evidentes de path traversal en la query
        dangerous_paths = ["../", "..\\", "%appdata%", "/etc/", "c:\\windows"]
        for p in dangerous_paths:
            if p in prompt_lower:
                logger.warning(f"Seguridad: Prompt bloqueado por intento de Path Traversal: '{p}'")
                return False, "Petición cancelada: Intento de Path Traversal detectado en la instrucción."

        return True, "OK"

    def is_destructive_action(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Determina si una llamada a herramienta representa un riesgo destructivo de alto impacto
        (e.g. eliminar carpetas completas del workspace o ejecutar comandos).

        Args:
            tool_name (str): Nombre de la herramienta.
            args (Dict): Argumentos.

        Returns:
            Tuple[bool, str]: (is_destructive, warning_message)
        """
        name_lower = tool_name.lower()

        # Comprobar delete/borrado
        if "delete" in name_lower or "remove" in name_lower:
            path = args.get("path") or args.get("target_path") or args.get("src")
            recursive = args.get("recursive", False)
            
            if recursive:
                return True, f"ADVERTENCIA DE SEGURIDAD: Se solicita la eliminación recursiva en '{path}'."
            return True, f"Se solicita eliminar el recurso en '{path}'."

        # Comprobar comando seguro de shell
        if "command" in name_lower or "shell" in name_lower:
            cmd = args.get("command") or args.get("cmd", "")
            return True, f"ADVERTENCIA DE SEGURIDAD: Ejecución de comando de consola '{cmd}'."

        # Comprobar sobrescritura masiva
        if "write" in name_lower and args.get("overwrite", False):
            path = args.get("path")
            return True, f"Sobrescritura del archivo '{path}'."

        return False, "Operación estándar."

    def validate_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Valida rigurosamente los argumentos de una llamada a herramienta provista
        por el modelo antes de que se ejecute en Python.

        Args:
            tool_name (str): Nombre de la herramienta a invocar.
            args (Dict[str, Any]): Argumentos generados por Gemini.

        Returns:
            Tuple[bool, str]: (is_authorized, reason)
        """
        # 1. Comprobar todos los argumentos que parezcan rutas de archivos o carpetas
        path_keys = ["path", "src", "dest", "source", "destination", "target_path", "excel_path", "source_folder", "dest_folder"]
        
        for key in path_keys:
            if key in args and args[key]:
                path_value = str(args[key])
                
                # Detectar path traversal obvio
                if self.security.detect_path_traversal(path_value):
                    logger.error(f"Seguridad: Intento de Path Traversal bloqueado en herramienta '{tool_name}' ({key}: '{path_value}')")
                    return False, f"Operación bloqueada: Path Traversal detectado en el parámetro '{key}'."

                # Comprobar si la ruta resuelve dentro del workspace
                secure_path = self.security.secure_path(path_value)
                if not secure_path:
                    logger.error(f"Seguridad: Ruta fuera del sandbox bloqueada en '{tool_name}' ({key}: '{path_value}')")
                    return False, f"Operación bloqueada: El parámetro '{key}' apunta a una ruta fuera del workspace autorizado."

        # 2. Comprobación específica para borrados críticos
        if "delete" in tool_name.lower():
            target_path = args.get("path") or args.get("target_path")
            if target_path:
                is_safe, msg = self.security.validate_delete(str(target_path))
                if not is_safe:
                    logger.error(f"Seguridad: Intento de borrar directorio núcleo bloqueado: {target_path}")
                    return False, f"Operación bloqueada: {msg}"

        # 3. Comprobación para comandos de consola
        if "command" in tool_name.lower():
            cmd = args.get("command") or args.get("cmd", "")
            
            # Prevenir caracteres encadenadores inyectados
            dangerous_chars = [";", "&&", "||", "|", "`", "$"]
            if any(char in cmd for char in dangerous_chars):
                logger.error(f"Seguridad: Intento de inyección de comandos bloqueado: '{cmd}'")
                return False, "Operación bloqueada: Caracteres encadenadores de procesos ilegales detectados."

        return True, "Autorizado."
