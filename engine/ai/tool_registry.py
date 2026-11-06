"""
======================================================================
MÓDULO: AGENT TOOL REGISTRY — Registro Avanzado de Herramientas IA
Archivo: ai/tool_registry.py
======================================================================
Responsabilidad:
- Registrar clases e instancias de capacidades modulares.
- Inspeccionar dinámicamente firmas, docstrings y tipos.
- Exponer herramientas estructuradas directamente compatibles con Gemini SDK.
- Enrutar de manera dinámica y segura invocaciones de herramientas (Tool Calling).
======================================================================
"""

import inspect
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Type

logger = logging.getLogger("FaceSync.ToolRegistry")


class AgentToolRegistry:
    """
    Registro inteligente de herramientas y capacidades del agente FaceSync.
    Permite registrar módulos de capacidad y mapear dinámicamente llamadas de la IA
    hacia funciones de Python reales de forma automatizada y segura.
    """

    def __init__(self):
        # Mapeo de nombre de herramienta -> (callable, metadata)
        self._registry: Dict[str, Dict[str, Any]] = {}
        # Lista de instancias registradas
        self._capabilities: List[Any] = []
        self.workspace_path: Optional[str] = None
        self.security_manager: Any = None

    def register(self, capability_instance: Any) -> None:
        """
        Registra todos los métodos públicos de una instancia de capacidad.
        Inspecciona dinámicamente y extrae los metadatos para la IA.

        Args:
            capability_instance: Instancia de clase de capacidad (e.g. FileCapabilities).
        """
        self._capabilities.append(capability_instance)
        cls_name = capability_instance.__class__.__name__
        logger.info(f"Registrando capacidades del componente: {cls_name}")

        # Obtener todos los métodos del objeto
        methods = inspect.getmembers(capability_instance, predicate=inspect.ismethod)

        for name, method in methods:
            # Ignorar métodos privados y especiales
            if name.startswith('_'):
                continue

            # Construir nombre calificado único o usar el simple si no colisiona
            tool_name = name
            if tool_name in self._registry:
                # Evitar colisión agregando prefijo del componente
                tool_name = f"{cls_name.lower().replace('capabilities', '')}_{name}"

            # Extraer docstring
            doc = inspect.getdoc(method) or "Sin descripción disponible."
            
            # Obtener firma para validar tipados
            sig = inspect.signature(method)
            
            self._registry[tool_name] = {
                "callable": method,
                "name": tool_name,
                "original_name": name,
                "description": doc.split('\n\n')[0],  # Primera línea como resumen
                "full_docstring": doc,
                "signature": sig,
                "component": cls_name
            }
            logger.debug(f"Herramienta registrada: '{tool_name}' ({cls_name}.{name})")

    def register_function(self, func: Callable[..., Any], name: Optional[str] = None) -> None:
        """
        Registra una funcion concreta como tool publica para Gemini.
        """

        tool_name = name or getattr(func, "__name__", None)
        if not tool_name:
            raise ValueError("La funcion registrada necesita un nombre.")

        doc = inspect.getdoc(func) or "Sin descripcion disponible."
        self._registry[tool_name] = {
            "callable": func,
            "name": tool_name,
            "original_name": tool_name,
            "description": doc.split("\n\n")[0],
            "full_docstring": doc,
            "signature": inspect.signature(func),
            "component": "GeminiWrappers"
        }

    def get_tool_names(self) -> List[str]:
        """
        Obtiene la lista de todas las herramientas registradas.
        """
        return list(self._registry.keys())

    def get_tool_callables(self) -> List[Callable[..., Any]]:
        """
        Retorna la lista de callables nativos listos para inyectarse directamente
        en la configuración de `tools` de la API de Google Gemini (GenAI Client).
        El SDK de Gemini lee los docstrings y firmas tipadas de Python automáticamente.

        Returns:
            List[Callable]: Lista de métodos ejecutables.
        """
        return [item["callable"] for item in self._registry.values()]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Genera esquemas JSON schema manuales de las herramientas. Útil si se requiere
        formatear para otros adaptadores de modelos que no leen firmas nativas de Python.

        Returns:
            List[Dict[str, Any]]: Esquemas de herramientas.
        """
        schemas = []
        for name, info in self._registry.items():
            sig = info["signature"]
            parameters = {
                "type": "OBJECT",
                "properties": {},
                "required": []
            }

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                # Mapear tipos de python a tipos JSON
                param_type = "string"
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == dict:
                    param_type = "object"
                elif param.annotation == list:
                    param_type = "array"

                parameters["properties"][param_name] = {
                    "type": param_type,
                    "description": f"Parámetro {param_name}"
                }

                if param.default == inspect.Parameter.empty:
                    parameters["required"].append(param_name)

            schemas.append({
                "name": name,
                "description": info["description"],
                "parameters": parameters
            })
        
        return schemas

    def execute(self, tool_name: str, **kwargs) -> Any:
        """
        Enruta y ejecuta dinámicamente una herramienta registrada por su nombre conceptual.

        Args:
            tool_name (str): Nombre de la herramienta invocada por la IA.
            kwargs: Argumentos mapeados provistos por el Tool Calling.

        Returns:
            Any: Resultado de la ejecución de la función Python.
        """
        if tool_name not in self._registry:
            raise KeyError(f"La herramienta '{tool_name}' no existe en el registro del agente.")

        tool_info = self._registry[tool_name]
        callable_func = tool_info["callable"]

        logger.info(f"IA invocando herramienta: '{tool_name}' de {tool_info['component']} con argumentos {kwargs}")
        
        try:
            # Invocar la función real de python
            result = callable_func(**kwargs)
            return result
        except Exception as e:
            logger.error(f"Error de ejecución en herramienta '{tool_name}': {e}", exc_info=True)
            return f"Error ejecutando '{tool_name}': {str(e)}"

    def auto_register_default_tools(
        self,
        workspace_path: str,
        security_manager: Any = None,
        account_id: str = "default",
    ) -> None:
        """
        Auto-registra wrappers simples y estables para Gemini.
        """
        try:
            from tools.file_tools import FileCapabilities
            from tools.document_tools import DocumentCapabilities
            from tools.search_tools import SearchCapabilities
            from tools.facesync_tools import FaceSyncCapabilities
            from tools.workspace_tools import WorkspaceCapabilities
        except ImportError as e:
            logger.error(f"Error importando herramientas: {e}")
            return

        self.workspace_path = str(Path(workspace_path).expanduser().resolve(strict=False))
        self.security_manager = security_manager
        self.account_id = str(account_id or "default").strip() or "default"
        if self.security_manager is not None and hasattr(self.security_manager, "set_project_root"):
            current_root = str(getattr(self.security_manager, "workspace_path", "") or "")
            if str(Path(current_root).resolve(strict=False)) != self.workspace_path:
                self.security_manager.set_project_root(self.workspace_path)

        file_cap = FileCapabilities(self.workspace_path, self.security_manager)
        document_cap = DocumentCapabilities(self.workspace_path, self.security_manager)
        search_cap = SearchCapabilities(self.workspace_path, self.security_manager)
        facesync_cap = FaceSyncCapabilities(
            self.workspace_path,
            self.security_manager,
            account_id=self.account_id,
        )
        workspace_cap = WorkspaceCapabilities(self.workspace_path, self.security_manager)

        self._capabilities.extend([
            file_cap,
            document_cap,
            search_cap,
            facesync_cap,
            workspace_cap,
        ])

        def crear_carpeta(path: str) -> str:
            """Accion de escritura bloqueada para tool-calling directo."""
            return self._blocked_pipeline_message("create_folder")

        def crear_archivo(path: str, content: str = "", overwrite: bool = False) -> str:
            """Accion de escritura bloqueada para tool-calling directo."""
            return self._blocked_pipeline_message("create_file")

        def borrar(path: str, recursive: bool = False) -> str:
            """
            Accion destructiva bloqueada para tool-calling directo. Usa el pipeline estructurado con confirmacion.
            """
            return self._blocked_pipeline_message("delete_item")

        def copiar(src: str, dest: str) -> str:
            """Accion de escritura bloqueada para tool-calling directo."""
            return self._blocked_pipeline_message("copy_item")

        def mover(src: str, dest: str) -> str:
            """Accion de escritura bloqueada para tool-calling directo."""
            return self._blocked_pipeline_message("move_item")

        def renombrar(path: str, new_name: str) -> str:
            """Accion de escritura bloqueada para tool-calling directo."""
            return self._blocked_pipeline_message("rename_item")

        def buscar_archivos(pattern: str = "*", extension: str = "", recursive: bool = True) -> str:
            """
            Busca archivos dentro del workspace por nombre/patron o por extension.
            """
            if extension:
                result = search_cap.search_by_extension(extension=extension, recursive=recursive)
            else:
                result = search_cap.search_by_name(pattern=pattern or "*", recursive=recursive)

            if not result.get("success"):
                return f"Error buscando archivos: {result.get('error', 'Desconocido')}"

            files = result.get("results", [])
            if not files:
                return "No se encontraron archivos."

            lines = [
                item.get("relative_path") or item.get("path") or item.get("name", "")
                for item in files[:100]
            ]
            return f"Archivos encontrados ({len(files)}):\n" + "\n".join(lines)

        def escanear_workspace() -> str:
            """
            Devuelve el arbol del workspace activo.
            """
            return workspace_cap.get_workspace_tree()

        def obtener_metricas_workspace() -> str:
            """
            Devuelve metricas locales del workspace activo.
            """
            return str(workspace_cap.get_workspace_metrics())

        def verificar_integridad_workspace() -> str:
            """
            Verifica integridad y aislamiento del workspace.
            """
            return str(workspace_cap.verify_integrity())

        def leer_archivo(path: str) -> str:
            """
            Lee un archivo/documento soportado dentro del workspace.
            """
            result = document_cap.read_document(path)
            if not result.get("success"):
                return f"Error leyendo archivo: {result.get('error', 'Desconocido')}"
            if result.get("type") in ("text", "pdf", "docx"):
                return result.get("content", "")
            return str(result)

        def leer_pdf(path: str) -> str:
            """
            Lee y extrae texto de un PDF dentro del workspace.
            """
            result = document_cap.read_pdf(path)
            if not result.get("success"):
                return f"Error leyendo PDF: {result.get('error', 'Desconocido')}"
            return result.get("content", "")

        def leer_excel(path: str, sheet_name: str = "") -> str:
            """
            Lee un archivo Excel dentro del workspace. sheet_name es opcional.
            """
            result = document_cap.read_excel(path, sheet_name=sheet_name or 0)
            if not result.get("success"):
                return f"Error leyendo Excel: {result.get('error', 'Desconocido')}"
            return str(result)

        def leer_documento(path: str) -> str:
            """
            Lee un documento soportado dentro del workspace: TXT, JSON, DOCX, PDF, CSV o Excel.
            """
            result = document_cap.read_document(path)
            if not result.get("success"):
                return f"Error leyendo documento: {result.get('error', 'Desconocido')}"
            return str(result)

        def crear_carpetas_desde_excel(excel_path: str, column: str = "", destination: str = "") -> str:
            """
            Accion masiva bloqueada para tool-calling directo. Usa el pipeline estructurado con preview.
            """
            return self._blocked_pipeline_message("create_folders_from_excel")

        def borrar_carpetas_desde_excel(excel_path: str, column: str = "", destination: str = "") -> str:
            """
            Accion destructiva bloqueada para tool-calling directo. Usa el pipeline estructurado con confirmacion.
            """
            return self._blocked_pipeline_message("delete_folders_from_excel")

        def crear_carpetas_desde_documento(document_path: str, mode: str = "auto", destination: str = "") -> str:
            """
            Accion masiva bloqueada para tool-calling directo. Usa el pipeline estructurado con preview.
            """
            return self._blocked_pipeline_message("create_folders_from_table")

        def ejecutar_facesync(
            excel_path: str,
            source_folder: str,
            dest_folder: str,
            name_column: str = "Nombre del Alumno",
            reference_column: str = "Foto",
        ) -> str:
            """
            Accion FaceSync bloqueada para tool-calling directo. Usa el pipeline estructurado con preview.
            """
            return self._blocked_pipeline_message("run_reference_face_matching")

        def run_reference_face_matching(
            table_path: str,
            name_column: str,
            reference_column: str,
            source_folder: str,
            destination_folder: str,
        ) -> str:
            """
            Accion FaceSync bloqueada para tool-calling directo. Usa el pipeline estructurado con preview.
            """
            return self._blocked_pipeline_message("run_reference_face_matching")

        def detectar_columnas_facesync(excel_path: str) -> str:
            """
            Detecta columnas de nombre de alumno y referencia de foto en un Excel/CSV.
            """
            return str(document_cap.detect_facesync_columns(excel_path))

        def estado_facesync() -> str:
            """
            Devuelve el estado local del motor FaceSync.
            """
            return str(facesync_cap.get_face_sync_status())

        for func in [
            buscar_archivos,
            escanear_workspace,
            obtener_metricas_workspace,
            verificar_integridad_workspace,
            leer_archivo,
            leer_pdf,
            leer_excel,
            leer_documento,
            detectar_columnas_facesync,
            estado_facesync,
        ]:
            self.register_function(func)

    @staticmethod
    def _blocked_pipeline_message(intent: str) -> str:
        return (
            f"La accion '{intent}' no se ejecuta directamente desde tool-calling. "
            "Debe pasar por FaceSyncDecision, ActionPlanner, PlanGuard y confirmacion."
        )

    def set_project_root(
        self,
        project_root: str,
        security_manager: Any = None,
        account_id: str | None = None,
    ) -> None:
        """
        Reconfigura el registro para que todas las closures usen el project_root activo.
        """
        self._registry.clear()
        self._capabilities.clear()
        self.auto_register_default_tools(
            project_root,
            security_manager or self.security_manager,
            account_id=account_id or getattr(self, "account_id", "default"),
        )

    def set_workspace(self, workspace_path: str, security_manager: Any = None) -> None:
        self.set_project_root(workspace_path, security_manager=security_manager)
