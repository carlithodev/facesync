"""
OpenAI fallback orchestrator for FaceSync AI.

This module only interprets user text into a small JSON contract. It never
executes tools, reads files, sends documents/images, or touches the workspace.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

from core.app_paths import private_env_path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency guard
    def load_dotenv(dotenv_path=None, override: bool = False):
        path = Path(dotenv_path or ".env")
        if not path.exists():
            return False
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if override or key not in os.environ:
                os.environ[key] = value
        return True


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENV_PATH = PROJECT_ROOT / ".env"
ENV_PATH = private_env_path() if private_env_path().is_file() else LEGACY_ENV_PATH
load_dotenv(ENV_PATH)


ALLOWED_OPENAI_INTENTS = {
    "greeting",
    "thanks",
    "farewell",
    "create_folder",
    "create_multiple_folders",
    "create_file",
    "read_document",
    "create_folders_from_excel",
    "create_folders_from_table",
    "prepare_facesync_pipeline",
    "excel_to_facesync_pipeline",
    "run_reference_face_matching",
    "classify_photos_by_reference",
    "move_item",
    "move_multiple_items",
    "copy_item",
    "copy_multiple_items",
    "rename_item",
    "delete_item",
    "delete_multiple_items",
    "delete_folders_from_excel",
    "search_files",
    "scan_workspace",
    "ask_missing_data",
    "unknown",
}


DEFAULT_ARGS = {
    "table_path": "",
    "excel_path": "",
    "excel_name": "",
    "name_column": "",
    "column_name": "",
    "reference_column": "",
    "source_folder": "",
    "destination_folder": "",
    "mode": "reference_face_matching",
    "folder_name": "",
    "file_name": "",
    "target": "",
    "source": "",
    "destination": "",
    "new_name": "",
    "quantity": None,
    "base_name": "",
    "content": "",
}


OPENAI_ORCHESTRATOR_PROMPT = """
Eres el orquestador de FaceSync AI.

Tu unico trabajo es convertir mensajes del usuario en una intencion estructurada
para que Python ejecute tools seguras.

No ejecutas codigo.
No procesas fotos.
No lees archivos completos.
No inventas rutas.
No modificas archivos.
No respondes con texto libre.
No usas shell.
No generas codigo.
No decides acciones destructivas sin confirmacion.

La app ya tiene herramientas Python para:
- crear carpetas
- crear multiples carpetas
- crear archivos
- mover
- renombrar
- borrar
- buscar
- escanear workspace
- leer Excel/PDF/TXT/CSV/JSON/DOCX
- crear carpetas desde Excel
- crear carpetas por cualquier columna de nombres
- ejecutar MotorFaceSync
- clasificar fotos por persona/entidad usando Excel/CSV y referencias faciales

Para ejecutar FaceSync en modo reference_face_matching se necesitan:
- table_path o excel_path
- name_column
- reference_column
- source_folder
- destination_folder

Si falta alguno, pregunta.
No preguntes todos los datos si solo falta uno.

La columna de referencia NO significa copiar solo esa foto.
Significa usar esa foto/codigo/archivo como rostro base de la persona y buscar
todas sus coincidencias en source_folder.

Nunca inventes rutas.
Las rutas pueden ser absolutas o relativas al workspace.
No pidas rutas absolutas si el contexto ya contiene un nombre de archivo/carpeta
valido para usar como ruta relativa.

Puedes usar archivos/carpetas mencionados por el usuario si aparecen en el
contexto disponible.
Si un nombre de archivo/carpeta aparece en available_files o available_folders,
consideralo una ruta relativa valida.
Si hay coincidencia clara por nombre parcial, usa el elemento completo del
contexto.
Si hay varias coincidencias posibles, pregunta aclaracion.

Reglas generales para table_path/excel_path:
- Puedes devolver table_path y excel_path si el usuario escribio explicitamente un archivo
  con extension .xlsx, .xls o .csv.
- Puedes devolver table_path y excel_path si el usuario menciona un nombre que coincide
  parcial o totalmente con context.available_files.
- Si el usuario dice "ese Excel", "la lista" o "ese archivo" y existe
  context.ultimo_excel_leido, usa ese valor.
- Si el usuario dice "el Excel de alumnos", "la lista de alumnos" o
  "archivo de alumnos" y hay un Excel probable en available_files, usa el
  archivo coincidente. No pidas ruta absoluta si hay coincidencia clara.

Reglas generales para name_column:
- Si el usuario indica una columna de nombres, devuelve exactamente ese texto.
- Puede llamarse Nombre, Alumno, Nombre del Alumno, Nombre completo,
  Estudiante, Persona, Cliente, Participante, Graduado o cualquier nombre que
  el usuario indique.

Reglas generales para reference_column:
- Si el usuario indica una columna de referencia/foto, devuelve exactamente
  ese texto.
- Puede llamarse Foto, Referencia, Foto referencia, ID Foto, Codigo de foto,
  Numero de foto, Imagen, Archivo o cualquier nombre que el usuario indique.
- Si el usuario dice "usando la columna X", "con la columna X",
  "segun la columna X", "basandote en X", "tomando X" o
  "X como referencia facial", coloca X en reference_column cuando el mensaje
  habla de reconocer/clasificar fotos por rostro o referencia.
- Esa parte nunca debe quedar pegada a destination_folder.

Reglas generales para source_folder:
- Puedes devolver source_folder si el usuario dice "las fotos estan en X",
  "toma las fotos de X", "usa las fotos de X", "carpeta de fotos X",
  "carpeta origen X" o "fotos originales X", y X aparece o coincide
  claramente con context.available_folders.
- Si el usuario dice "esa carpeta de fotos" y existe
  context.ultima_carpeta_fotos, usa ese valor.
- Si el usuario dice "las fotos estan ahi" y existe context.active_path,
  usa active_path.

Reglas generales para destination_folder:
- Puedes devolver destination_folder si el usuario dice "guarda en X",
  "mandalas a X", "metelas en X", "resultado en X", "carpeta destino X",
  "clasificadas en X" o "ponlas en X", y X aparece o coincide claramente
  con context.available_folders.
- Al extraer X, corta antes de conectores como "usando", "con la columna",
  "con columna", "basandote", "tomando", "segun", "conforme a",
  "de acuerdo a", "como referencia", "para reconocer" o "para clasificar".
- Ejemplo: "dentro de la carpeta Resultado usando la columna Foto" produce
  destination_folder="Resultado" y reference_column="Foto".
- Si el usuario da claramente un nombre de carpeta destino que no aparece en
  available_folders, puedes devolverlo como ruta relativa, pero marca
  needs_clarification=true o safe_to_execute=false si la app debe confirmar
  si desea crearla.
- Si el usuario dice "guardalas ahi" y existe context.ultima_carpeta_destino
  o context.active_path, usa ese valor.

Si el usuario dice "ese Excel", usa el contexto si existe.
Si el usuario dice "ahi", usa active_path/ultima_carpeta_destino si existe.
Si no hay datos suficientes, needs_clarification=true.

Devuelve solo JSON valido.
""".strip()


class OpenAIOrchestrator:
    def __init__(self, api_key: str, model: str = "gpt-5.4-mini"):
        load_dotenv(ENV_PATH)

        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = (model or os.getenv("OPENAI_MODEL_FAST") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
        self.enabled = self._env_bool("USE_OPENAI_ORCHESTRATOR", default=False)
        self.only_fallback = self._env_bool("OPENAI_ORCHESTRATOR_ONLY_FALLBACK", default=True)
        self.max_monthly_usd = (os.getenv("OPENAI_MONTHLY_SOFT_LIMIT_USD") or os.getenv("OPENAI_MAX_MONTHLY_USD") or "5").strip()
        self._client = None
        self._disabled_logged = False
        self._log_env_state()

    @classmethod
    def from_env(cls) -> "OpenAIOrchestrator":
        load_dotenv(ENV_PATH)
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL_FAST") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        )

    def is_available(self) -> bool:
        available = bool(self.enabled and self.api_key)
        if not available and not self._disabled_logged:
            print("[OPENAI_ORCH] deshabilitado o sin API key")
            self._disabled_logged = True
        return available

    def _log_env_state(self):
        print(f"[OPENAI_ORCH] env USE_OPENAI_ORCHESTRATOR={str(self.enabled).lower()}")
        print(f"[OPENAI_ORCH] api_key_present={bool(self.api_key)}")
        print(f"[OPENAI_ORCH] model={self.model}")

    def interpret(
        self,
        user_text: str,
        context: dict,
        local_guess: dict | None = None,
    ) -> dict:
        if not self.is_available():
            return self._unknown("OpenAIOrchestrator deshabilitado o sin API key.")

        try:
            client = self._get_client()
        except Exception as exc:
            print(f"[OPENAI_ORCH] deshabilitado o sin API key: {exc}")
            return self._unknown(str(exc))

        payload = {
            "mensaje_usuario": str(user_text or "")[:1200],
            "contexto_resumido": self._compact_context(context),
            "local_guess": self._compact_local_guess(local_guess),
            "intents_permitidos": sorted(ALLOWED_OPENAI_INTENTS),
            "formato_json_obligatorio": {
                "intent": "classify_photos_by_reference",
                "confidence": 0.92,
                "needs_clarification": False,
                "question": "",
                "args": dict(DEFAULT_ARGS),
                "reason": "",
                "safe_to_execute": True,
                "model_used": self.model,
                "escalation_reason": "",
            },
        }

        print(f"[OPENAI_ORCH] called model={self.model}")
        try:
            raw_response = self._call_openai(client, payload)
            usage = raw_response.get("usage") or {}
            text = raw_response.get("text") or ""
            parsed = self._parse_json(text)
            parsed = self._with_default_shape(parsed)
            parsed = self._normalize_paths_from_context(parsed, payload["contexto_resumido"])
            parsed["model_used"] = parsed.get("model_used") or self.model
            parsed["escalation_reason"] = parsed.get("escalation_reason") or ""

            print(f"[OPENAI_ORCH] intent={parsed.get('intent')} confidence={parsed.get('confidence')}")
            print(f"[OPENAI_ORCH] needs_clarification={parsed.get('needs_clarification')}")
            print(f"[OPENAI_ORCH] safe_to_execute={parsed.get('safe_to_execute')}")
            print(f"[OPENAI_ORCH] tokens_input={usage.get('tokens_input', 0)}")
            print(f"[OPENAI_ORCH] tokens_output={usage.get('tokens_output', 0)}")
            return parsed
        except Exception as exc:
            print(f"[OPENAI_ORCH] error={type(exc).__name__}: {exc}")
            return self._unknown(str(exc))

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except Exception as exc:
            print(f"[OPENAI_ORCH] SDK openai no disponible; usando HTTP directo: {exc}")
            self._client = "raw_http"
            return self._client
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _call_openai(
        self,
        client: Any,
        payload: Dict[str, Any],
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        model = (model or self.model).strip()
        messages = [
            {"role": "system", "content": system_prompt or OPENAI_ORCHESTRATOR_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

        if client == "raw_http":
            return self._call_openai_http(messages, model=model)

        if hasattr(client, "responses"):
            try:
                response = client.responses.create(
                    model=model,
                    input=messages,
                    text={"format": {"type": "json_object"}},
                    max_output_tokens=900,
                )
                return {
                    "text": getattr(response, "output_text", "") or self._extract_responses_text(response),
                    "usage": self._extract_usage(getattr(response, "usage", None)),
                }
            except TypeError:
                response = client.responses.create(model=model, input=messages, max_output_tokens=900)
                return {
                    "text": getattr(response, "output_text", "") or self._extract_responses_text(response),
                    "usage": self._extract_usage(getattr(response, "usage", None)),
                }

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            max_completion_tokens=900,
        )
        choice = response.choices[0]
        return {
            "text": choice.message.content or "",
            "usage": self._extract_usage(getattr(response, "usage", None)),
        }

    def _call_openai_http(self, messages: list[dict], model: Optional[str] = None) -> Dict[str, Any]:
        import urllib.error
        import urllib.request

        body = {
            "model": (model or self.model).strip(),
            "input": messages,
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": 900,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc

        return {
            "text": data.get("output_text") or self._extract_responses_text_from_dict(data),
            "usage": self._extract_usage(data.get("usage")),
        }

    @staticmethod
    def _extract_responses_text_from_dict(data: Dict[str, Any]) -> str:
        chunks = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text") if isinstance(content, dict) else None
                if text:
                    chunks.append(text)
        return "\n".join(chunks)

    @staticmethod
    def _extract_responses_text(response: Any) -> str:
        chunks = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(text)
        return "\n".join(chunks)

    @staticmethod
    def _extract_usage(usage: Any) -> Dict[str, int]:
        if not usage:
            return {"tokens_input": 0, "tokens_output": 0}
        if isinstance(usage, dict):
            return {
                "tokens_input": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
                "tokens_output": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            }
        return {
            "tokens_input": int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0),
            "tokens_output": int(getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0),
        }

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[4:].strip() if raw.lower().startswith("json") else raw
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end >= start:
            raw = raw[start : end + 1]
        return json.loads(raw)

    @classmethod
    def _with_default_shape(cls, parsed: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            return cls._unknown("La respuesta no fue un objeto JSON.")

        shaped = {
            "intent": str(parsed.get("intent") or "unknown"),
            "confidence": parsed.get("confidence", 0.0),
            "needs_clarification": parsed.get("needs_clarification", True),
            "question": str(parsed.get("question") or ""),
            "args": parsed.get("args") if isinstance(parsed.get("args"), dict) else {},
            "reason": str(parsed.get("reason") or ""),
            "safe_to_execute": parsed.get("safe_to_execute", False),
            "model_used": str(parsed.get("model_used") or ""),
            "escalation_reason": str(parsed.get("escalation_reason") or ""),
        }
        if shaped["intent"] != "unknown":
            args = dict(DEFAULT_ARGS)
            args.update(shaped["args"])
            shaped["args"] = args
        return shaped

    @classmethod
    def _normalize_paths_from_context(cls, response: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(response, dict) or not isinstance(response.get("args"), dict):
            return response

        args = dict(response["args"])
        available_files = cls._as_list(context.get("available_files"))
        available_folders = cls._as_list(context.get("available_folders"))

        excel_candidates = available_files + cls._context_values(
            context,
            "ultimo_excel_leido",
            "last_excel",
        )
        source_candidates = available_folders + cls._context_values(
            context,
            "ultima_carpeta_fotos",
        )
        destination_candidates = available_folders + cls._context_values(
            context,
            "ultima_carpeta_destino",
            "active_path",
        )

        table_value = args.get("table_path") or args.get("excel_path") or args.get("excel_name")
        resolved_table = cls._resolve_clear_context_match(table_value, excel_candidates, extensions={".xlsx", ".xls", ".csv"})
        args["table_path"] = resolved_table
        args["excel_path"] = resolved_table
        if args.get("excel_name"):
            args["excel_name"] = cls._resolve_clear_context_match(args.get("excel_name"), excel_candidates, extensions={".xlsx", ".xls", ".csv"})
        elif resolved_table:
            args["excel_name"] = resolved_table

        args["source_folder"] = cls._resolve_clear_context_match(args.get("source_folder"), source_candidates)
        args["destination_folder"] = cls._resolve_clear_context_match(
            cls._strip_destination_tail(args.get("destination_folder")),
            destination_candidates,
        )

        response["args"] = args
        return response

    @staticmethod
    def _strip_destination_tail(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        patterns = [
            r"\s+usando\s+.+$",
            r"\s+usa\s+.+$",
            r"\s+con\s+la\s+columna\s+.+$",
            r"\s+con\s+columna\s+.+$",
            r"\s+bas[aá]ndote\s+.+$",
            r"\s+basado\s+en\s+.+$",
            r"\s+tomando\s+.+$",
            r"\s+seg[uú]n\s+.+$",
            r"\s+conforme\s+a\s+.+$",
            r"\s+de\s+acuerdo\s+a\s+.+$",
            r"\s+como\s+referencia.*$",
            r"\s+para\s+reconocer\s+.+$",
            r"\s+para\s+clasificar\s+.+$",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        return text

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)]

    @classmethod
    def _context_values(cls, context: Dict[str, Any], *keys: str) -> list[str]:
        values = []
        for key in keys:
            value = context.get(key)
            if value:
                values.extend(cls._as_list(value))
        return values

    @classmethod
    def _resolve_clear_context_match(
        cls,
        value: Any,
        candidates: list[str],
        *,
        extensions: Optional[set[str]] = None,
    ) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""

        if extensions and Path(raw).suffix.lower() in extensions:
            exact = cls._find_best_context_match(raw, candidates)
            return exact or raw

        best = cls._find_best_context_match(raw, candidates)
        return best or raw

    @classmethod
    def _find_best_context_match(cls, query: str, candidates: list[str]) -> str:
        query_norm = cls._norm_path_text(query)
        if not query_norm:
            return ""

        query_tokens = set(query_norm.split())
        scored: list[tuple[int, str]] = []
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            candidate_norm = cls._norm_path_text(candidate)
            candidate_stem_norm = cls._norm_path_text(Path(candidate).stem)
            candidate_tokens = set(candidate_norm.split())
            score = 0
            if query_norm == candidate_norm or query_norm == candidate_stem_norm:
                score += 100
            elif query_norm in candidate_norm or query_norm in candidate_stem_norm:
                score += 70
            elif candidate_stem_norm and candidate_stem_norm in query_norm:
                score += 60
            overlap = len(query_tokens & candidate_tokens)
            if overlap:
                score += overlap * 15
            if query_tokens and query_tokens.issubset(candidate_tokens):
                score += 35
            if score > 0:
                scored.append((score, candidate))

        if not scored:
            return ""

        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    @staticmethod
    def _norm_path_text(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _compact_context(context: Any) -> Dict[str, Any]:
        keys = [
            "ultimo_excel_leido",
            "last_excel",
            "ultima_carpeta_fotos",
            "ultima_carpeta_destino",
            "available_files",
            "available_folders",
            "ultimo_facesync_plan",
            "pending_action",
            "ultimo_intent",
            "ultimo_documento_leido",
            "ultima_busqueda",
            "ultimos_resultados_busqueda",
        ]
        source = context or {}
        if hasattr(source, "current_context"):
            source = getattr(source, "current_context")
        compact = {}
        project_root = source.get("project_root") or source.get("workspace_actual") or source.get("workspace") if isinstance(source, dict) else None
        active_path = source.get("active_path") if isinstance(source, dict) else None
        if project_root:
            compact["project_root_name"] = Path(str(project_root)).name or str(project_root)
        if active_path:
            compact["active_path_name"] = Path(str(active_path)).name or str(active_path)
            try:
                compact["active_path"] = str(
                    Path(str(active_path)).resolve(strict=False).relative_to(
                        Path(str(project_root)).resolve(strict=False)
                    )
                ).replace("\\", "/") if project_root else Path(str(active_path)).name
            except Exception:
                compact["active_path"] = Path(str(active_path)).name or str(active_path)
        for key in keys:
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                value = value[:8]
            if isinstance(value, dict):
                value = {k: value.get(k) for k in list(value.keys())[:12]}
            if value or key in {"available_files", "available_folders"}:
                compact[key] = value
        return compact

    @staticmethod
    def _compact_local_guess(local_guess: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not local_guess:
            return {}
        return {
            "intent": local_guess.get("intent", "unknown"),
            "confidence": local_guess.get("confidence", 0.0),
            "needs_clarification": local_guess.get("needs_clarification", False),
            "args": local_guess.get("args", {}),
            "reason": local_guess.get("reason", ""),
            "source": local_guess.get("source", ""),
        }

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}

    @staticmethod
    def _unknown(reason: str = "") -> Dict[str, Any]:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "needs_clarification": True,
            "question": "¿Puedes indicarme qué quieres hacer exactamente?",
            "args": {},
            "reason": reason or "No se pudo determinar una acción segura.",
            "safe_to_execute": False,
            "model_used": "",
            "escalation_reason": "",
        }
