"""
Natural Spanish responses for local tool execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


class ResponseFormatter:
    # Marcador que el chat (frontend) convierte en botones de "siguiente paso".
    # Formato:  <texto>\n[[OPC]]opcion 1|opcion 2|opcion 3
    OPC = "[[OPC]]"

    @classmethod
    def format(cls, result: Dict[str, Any]) -> str:
        text = cls._format_impl(result)
        # Solo cuando la accion termino bien y no estamos pidiendo un dato:
        if result.get("success") and not result.get("requires_clarification"):
            action = result.get("action") or result.get("intent") or ""
            options = cls._options_for(action, result.get("data") or {})
            if options:
                text = f"{text}\n{cls.OPC}" + "|".join(options)
        return text

    # Sugerencias de siguiente paso por tarea. Cortas, accionables y en frases
    # que el propio asistente entiende al reenviarlas.
    @classmethod
    def _options_for(cls, action: str, data: Dict[str, Any]) -> list:
        if action == "read_document":
            doc_type = (data.get("document") or {}).get("type")
            if doc_type in ("excel", "csv"):
                return ["Crear carpetas con este Excel", "Clasificar fotos con este Excel"]
            return ["Escanear el workspace"]
        table = {
            "create_folders_from_excel": ["Clasificar fotos ahora", "Abrir la carpeta destino"],
            "create_folders_from_table": ["Clasificar fotos ahora", "Abrir la carpeta destino"],
            "create_folder": ["Crear otra carpeta", "Agregar archivos"],
            "create_multiple_folders": ["Clasificar fotos ahora", "Escanear el workspace"],
            "create_file": ["Crear otro archivo", "Crear una carpeta"],
            "create_multiple_files": ["Escanear el workspace"],
            "move_item": ["Escanear el workspace"],
            "move_multiple_items": ["Escanear el workspace"],
            "copy_item": ["Escanear el workspace"],
            "copy_multiple_items": ["Escanear el workspace"],
            "rename_item": ["Escanear el workspace"],
            "delete_item": ["Escanear el workspace"],
            "delete_multiple_items": ["Escanear el workspace"],
            "delete_folders_from_excel": ["Escanear el workspace"],
            "search_files": ["Refinar la busqueda", "Escanear el workspace"],
            "scan_workspace": ["Leer un Excel", "Clasificar fotos"],
            "excel_to_facesync_pipeline": ["Ver el reporte", "Exportar a Drive"],
            "prepare_facesync_pipeline": ["Ver el reporte", "Exportar a Drive"],
            "run_facesync": ["Ver el reporte", "Exportar a Drive"],
            "run_reference_face_matching": ["Ver el reporte", "Exportar a Drive"],
            "classify_photos_by_reference": ["Ver el reporte", "Exportar a Drive"],
        }
        return table.get(action, [])

    @classmethod
    def _format_impl(cls, result: Dict[str, Any]) -> str:
        if result.get("requires_clarification"):
            return cls.clarification(result.get("question") or "Me falta un dato para continuar.")

        if not result.get("success", False):
            return cls.error(result)

        action = result.get("action") or result.get("intent") or ""
        data = result.get("data") or {}

        if action == "create_folder":
            folder = data.get("folder_name") or Path(str(data.get("path", ""))).name
            destination = cls._destination_label(data)
            if destination in {"", ".", "carpeta principal"}:
                return f"Listo, creé la carpeta '{folder}' en la carpeta principal."
            if destination in {"aqui", "aquí", "carpeta seleccionada"}:
                return f"Listo, creé la carpeta '{folder}' aqui."
            return f"Listo, creé la carpeta '{folder}' dentro de '{destination}'."

        if action == "create_multiple_folders":
            return cls._format_created_range(data, singular="carpeta", plural="carpetas")

        if action == "create_file":
            file_name = data.get("file_name") or Path(str(data.get("path", ""))).name
            destination = cls._destination_label(data)
            if destination in {"", ".", "carpeta principal"}:
                return f"Listo, creé el archivo '{file_name}' en la carpeta principal."
            if destination in {"aqui", "aquí", "carpeta seleccionada"}:
                return f"Listo, creé el archivo '{file_name}' aqui."
            return f"Listo, creé el archivo '{file_name}' dentro de '{destination}'."

        if action == "create_multiple_files":
            return cls._format_created_range(data, singular="archivo", plural="archivos")

        if action == "move_item":
            source = data.get("source") or data.get("target")
            destination = data.get("destination") or data.get("destination_folder")
            return f"Perfecto, moví '{source}' a '{destination}'."

        if action == "move_multiple_items":
            return f"Perfecto, movi los elementos indicados a '{data.get('destination')}'."

        if action == "copy_item":
            source = data.get("source") or data.get("target")
            destination = data.get("destination") or data.get("destination_folder")
            return f"Perfecto, copié '{source}' a '{destination}'."

        if action == "copy_multiple_items":
            return f"Perfecto, copie los elementos indicados a '{data.get('destination')}'."

        if action == "rename_item":
            return f"Listo, renombre '{data.get('target')}' a '{data.get('new_name')}'."

        if action == "delete_item":
            return f"Listo, elimine '{data.get('target')}'."

        if action == "delete_multiple_items":
            return "Listo, elimine los elementos indicados."

        if action == "delete_folders_from_excel":
            report = data.get("delete_report") or data
            deleted = report.get("deleted", data.get("deleted_count", 0))
            destination = report.get("destination") or data.get("destination_folder") or "."
            destination_label = cls._human_destination(destination)
            return (
                f"Listo, elimine {deleted} carpeta(s) generadas desde el Excel. "
                f"Destino revisado: {destination_label}."
            )

        if action == "search_files":
            results = data.get("results") or []
            if not results:
                return "No encontre archivos con ese criterio."
            lines = [item.get("relative_path") or item.get("path") or item.get("name", "") for item in results[:25]]
            return f"Encontre {len(results)} resultado(s):\n" + "\n".join(lines)

        if action == "scan_workspace":
            return data.get("tree") or result.get("message") or "Listo, escanee el workspace."

        if action == "read_document":
            return cls._format_read_document(data)

        if action in ("create_folders_from_excel", "create_folders_from_table"):
            return cls._format_excel_folders(data)

        if action in (
            "excel_to_facesync_pipeline",
            "prepare_facesync_pipeline",
            "run_facesync",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        ):
            return cls._format_facesync(data, action)

        return result.get("message") or "Listo, accion completada."

    @staticmethod
    def clarification(question: str) -> str:
        return question.strip()

    @staticmethod
    def _destination_label(data: Dict[str, Any]) -> str:
        destination = str(data.get("destination_label") or data.get("destination") or data.get("destination_folder") or "").strip()
        return destination or "carpeta principal"

    @staticmethod
    def _human_destination(destination: Any) -> str:
        text = str(destination or "").strip()
        if text in {"", ".", "carpeta principal"}:
            return "carpeta principal"
        if text in {"aqui", "aquí", "carpeta seleccionada"}:
            return "aqui"
        return text

    @classmethod
    def _format_created_range(cls, data: Dict[str, Any], *, singular: str, plural: str) -> str:
        paths = [str(path) for path in (data.get("paths") or []) if path]
        count = data.get("created_count") or len(paths)
        noun = singular if count == 1 else plural
        destination = cls._destination_label(data)

        if paths:
            first_name = Path(paths[0]).name
            last_name = Path(paths[-1]).name
            range_text = first_name if first_name == last_name else f"{first_name} a {last_name}"
        else:
            range_text = str(data.get("base_name") or "").strip()

        if destination in {"", ".", "carpeta principal"}:
            return f"Listo, cree {count} {noun} en la carpeta principal: {range_text}."
        if destination in {"aqui", "aquí", "carpeta seleccionada"}:
            return f"Listo, cree {count} {noun} aqui: {range_text}."
        return f"Listo, cree {count} {noun} dentro de '{destination}': {range_text}."

    @staticmethod
    def error(result: Dict[str, Any]) -> str:
        action = result.get("action") or result.get("intent") or "la accion"
        error = result.get("error") or result.get("message") or "Error desconocido"
        if action in (
            "excel_to_facesync_pipeline",
            "prepare_facesync_pipeline",
            "run_facesync",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        ):
            return f"Te entendi, pero no pude iniciar FaceSync: {error}"
        return f"No pude completar {action}: {error}"

    @classmethod
    def _format_read_document(cls, data: Dict[str, Any]) -> str:
        path = data.get("path") or "el documento"
        doc = data.get("document") or {}
        doc_type = doc.get("type")

        name = Path(str(path)).name or path

        if doc_type in ("excel", "csv"):
            columns = ", ".join(map(str, doc.get("columns", [])))
            rows = doc.get("rows", 0)
            return f"Listo, leí {name}: {rows} fila(s) y {len(doc.get('columns', []))} columna(s) ({columns})."

        if doc_type == "pdf":
            pages = doc.get("pages")
            extra = f", {pages} pagina(s)" if pages else ""
            return f"Listo, leí {name}{extra}. Ya tengo su contenido."

        if doc_type == "json":
            return f"Listo, leí {name}. Ya tengo su contenido JSON."

        if doc.get("content") is not None:
            return f"Listo, leí {name}. Ya tengo su contenido."
        return f"Listo, leí {name}."

    @classmethod
    def _format_excel_folders(cls, data: Dict[str, Any]) -> str:
        report = data.get("folder_report") or data
        excel = data.get("excel_path") or report.get("source") or "el Excel"
        rows = data.get("rows") or report.get("total_rows") or 0
        created = report.get("created", report.get("folders_created", 0))
        reused = report.get("reused", [])
        created_count = len(created) if isinstance(created, list) else int(created or 0)
        reused_count = len(reused) if isinstance(reused, list) else int(reused or 0)
        column = data.get("name_column") or report.get("column_used") or "la columna detectada"
        destination = report.get("destination") or data.get("destination") or "."
        destination_label = cls._human_destination(destination)
        reused_text = f" y reutilice {reused_count}" if reused_count else ""
        return (
            f"Perfecto, lei {excel}, detecte {rows} registro(s), cree {created_count} carpeta(s){reused_text} "
            f"usando la columna '{column}'. Destino: {destination_label}."
        )

    @classmethod
    def _format_facesync(cls, data: Dict[str, Any], action: str) -> str:
        excel = data.get("table_path") or data.get("excel_path") or "el Excel/CSV"
        rows = data.get("rows") or 0
        name_column = data.get("name_column") or "la columna de nombres"
        reference_column = data.get("reference_column") or "la columna de referencia"
        source = data.get("source_folder") or "la carpeta de fotos"
        destination = data.get("destination_folder") or "."
        destination_label = cls._human_destination(destination)
        created = data.get("folders_created")
        folder_part = f" y cree {created} carpeta(s)" if created is not None else ""
        prefix = "Perfecto" if action == "excel_to_facesync_pipeline" else "Listo"
        return (
            f"{prefix}. Usare el Excel '{excel}', tomare las fotos desde '{source}' "
            f"y guardare el resultado en '{destination_label}'. Detecte {rows} registro(s){folder_part}; "
            f"usare '{name_column}' para las carpetas y '{reference_column}' como referencia facial. "
            "Iniciare el reconocimiento facial. Las fotos originales no se modificaran."
        )

    @staticmethod
    def _truncate(content: str, limit: int = 4000) -> str:
        content = content or ""
        if len(content) <= limit:
            return content
        return content[:limit] + "\n\n[Contenido truncado para proteger el contexto.]"
