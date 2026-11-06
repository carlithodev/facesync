
"""
======================================================================
MÓDULO: MEMORY MANAGER — FaceSync AI
Archivo: core/memory_manager.py
======================================================================

Responsabilidad:
- Gestionar memoria conversacional del agente
- Guardar contexto reciente
- Recordar acciones anteriores
- Mantener historial inteligente
- Persistir memoria en disco
- Crear memoria temporal y permanente

Este módulo NO depende de Gemini.
Es la memoria local del agente.

======================================================================
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional


class MemoryManager:
    """
    Sistema de memoria híbrida.

    Tipos de memoria:
    - short_term_memory
    - long_term_memory
    - execution_history
    - workspace_memory
    """

    # ==========================================================
    # INIT
    # ==========================================================

    def __init__(self, memory_path: str = "cache/memory"):
        self.memory_path = memory_path

        os.makedirs(self.memory_path, exist_ok=True)

        # memoria RAM
        self.short_term_memory = []

        # archivos persistentes
        self.conversation_file = os.path.join(
            self.memory_path,
            "conversation_memory.json"
        )

        self.execution_file = os.path.join(
            self.memory_path,
            "execution_history.json"
        )

        self.workspace_file = os.path.join(
            self.memory_path,
            "workspace_memory.json"
        )

        self.preferences_file = os.path.join(
            self.memory_path,
            "user_preferences.json"
        )

        # cargar memoria
        self.long_term_memory = self._load_json(self.conversation_file)
        self.execution_history = self._load_json(self.execution_file)
        self.workspace_memory = self._load_json(self.workspace_file)
        self.preferences = self._load_json(self.preferences_file)

    # ==========================================================
    # SHORT TERM MEMORY
    # ==========================================================

    def add_message(self, role: str, content: str):
        """
        Agrega mensaje reciente a memoria temporal.
        """

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        self.short_term_memory.append(message)

        # limitar memoria temporal
        MAX_SHORT_MEMORY = 20

        if len(self.short_term_memory) > MAX_SHORT_MEMORY:
            self.short_term_memory.pop(0)

    def get_recent_context(self, limit: int = 10) -> List[Dict]:
        """
        Devuelve contexto reciente.
        """

        return self.short_term_memory[-limit:]

    def clear_short_memory(self):
        """
        Limpia memoria temporal.
        """

        self.short_term_memory.clear()

    # ==========================================================
    # LONG TERM MEMORY
    # ==========================================================

    def save_conversation(self, user_message: str, assistant_response: str):
        """
        Guarda conversación persistente.
        """

        data = {
            "timestamp": datetime.now().isoformat(),
            "user": user_message,
            "assistant": assistant_response
        }

        self.long_term_memory.append(data)

        self._save_json(
            self.conversation_file,
            self.long_term_memory
        )

    def search_memory(self, keyword: str) -> List[Dict]:
        """
        Busca conversaciones anteriores.
        """

        results = []

        keyword = keyword.lower()

        for item in self.long_term_memory:

            user_text = item.get("user", "").lower()
            assistant_text = item.get("assistant", "").lower()

            if keyword in user_text or keyword in assistant_text:
                results.append(item)

        return results

    # ==========================================================
    # EXECUTION HISTORY
    # ==========================================================

    def add_execution(
        self,
        action: str,
        status: str,
        details: Dict = None
    ):
        """
        Guarda acciones ejecutadas.
        """

        execution = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "status": status,
            "details": details or {}
        }

        self.execution_history.append(execution)

        # limitar historial
        MAX_HISTORY = 500

        if len(self.execution_history) > MAX_HISTORY:
            self.execution_history.pop(0)

        self._save_json(
            self.execution_file,
            self.execution_history
        )

    def get_last_execution(self) -> Optional[Dict]:
        """
        Obtiene última acción ejecutada.
        """

        if not self.execution_history:
            return None

        return self.execution_history[-1]

    def get_failed_executions(self) -> List[Dict]:
        """
        Devuelve ejecuciones fallidas.
        """

        return [
            item
            for item in self.execution_history
            if item.get("status") == "error"
        ]

    # ==========================================================
    # WORKSPACE MEMORY
    # ==========================================================

    def save_workspace_snapshot(
        self,
        workspace_path: str,
        files: List[str],
        folders: List[str]
    ):
        """
        Guarda snapshot del workspace.
        """

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "workspace": workspace_path,
            "files": files,
            "folders": folders
        }

        self.workspace_memory = snapshot

        self._save_json(
            self.workspace_file,
            self.workspace_memory
        )

    def get_workspace_snapshot(self) -> Dict:
        """
        Obtiene snapshot guardado.
        """

        return self.workspace_memory

    # ==========================================================
    # USER PREFERENCES
    # ==========================================================

    def set_preference(self, key: str, value):
        """
        Guarda preferencias del usuario.
        """

        self.preferences[key] = value

        self._save_json(
            self.preferences_file,
            self.preferences
        )

    def get_preference(self, key: str, default=None):
        """
        Obtiene preferencia.
        """

        return self.preferences.get(key, default)

    # ==========================================================
    # CONTEXT BUILDING
    # ==========================================================

    def build_context_prompt(self) -> str:
        """
        Construye contexto para IA.
        """

        lines = []

        lines.append("=== MEMORIA RECIENTE ===")

        recent = self.get_recent_context(5)

        for msg in recent:
            role = msg["role"]
            content = msg["content"]

            lines.append(f"{role}: {content}")

        lines.append("\n=== ÚLTIMAS EJECUCIONES ===")

        last_executions = self.execution_history[-5:]

        for item in last_executions:
            lines.append(
                f"{item['action']} → {item['status']}"
            )

        lines.append("\n=== PREFERENCIAS ===")

        for key, value in self.preferences.items():
            lines.append(f"{key}: {value}")

        return "\n".join(lines)

    # ==========================================================
    # SMART MEMORY
    # ==========================================================

    def remember_success_pattern(
        self,
        user_request: str,
        successful_action: str
    ):
        """
        Aprende patrones exitosos.
        """

        patterns_file = os.path.join(
            self.memory_path,
            "patterns.json"
        )

        patterns = self._load_json(patterns_file)

        patterns.append({
            "request": user_request,
            "action": successful_action,
            "timestamp": datetime.now().isoformat()
        })

        self._save_json(patterns_file, patterns)

    def get_similar_patterns(
        self,
        query: str
    ) -> List[Dict]:
        """
        Busca patrones similares.
        """

        patterns_file = os.path.join(
            self.memory_path,
            "patterns.json"
        )

        patterns = self._load_json(patterns_file)

        query = query.lower()

        results = []

        for pattern in patterns:

            request = pattern.get("request", "").lower()

            if query in request:
                results.append(pattern)

        return results

    # ==========================================================
    # JSON HELPERS
    # ==========================================================

    def _load_json(self, path: str):
        """
        Carga JSON seguro.
        """

        try:

            if not os.path.exists(path):
                return []

            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception:
            return []

    def _save_json(self, path: str, data):
        """
        Guarda JSON seguro.
        """

        try:

            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

        except Exception as e:
            print(f"Error guardando memoria: {e}")

    # ==========================================================
    # RESET MEMORY
    # ==========================================================

    def reset_all_memory(self):
        """
        Reinicia toda la memoria.
        """

        self.short_term_memory = []
        self.long_term_memory = []
        self.execution_history = []
        self.workspace_memory = {}
        self.preferences = {}

        files = [
            self.conversation_file,
            self.execution_file,
            self.workspace_file,
            self.preferences_file
        ]

        for file in files:
            try:
                if os.path.exists(file):
                    os.remove(file)
            except:
                pass

    # ==========================================================
    # DEBUG
    # ==========================================================

    def debug_memory(self):
        """
        Debug completo.
        """

        print("\n" + "=" * 60)
        print("MEMORY MANAGER DEBUG")
        print("=" * 60)

        print(f"\nShort memory: {len(self.short_term_memory)}")
        print(f"Long memory: {len(self.long_term_memory)}")
        print(f"Executions: {len(self.execution_history)}")

        print("\nPreferences:")
        print(self.preferences)

        print("\nWorkspace snapshot:")
        print(self.workspace_memory)

        print("=" * 60)


# ==============================================================
# TEST LOCAL
# ==============================================================

if __name__ == "__main__":

    memory = MemoryManager()

    memory.add_message(
        "user",
        "Créame una carpeta llamada ventas"
    )

    memory.add_message(
        "assistant",
        "Carpeta creada correctamente"
    )

    memory.save_conversation(
        "hola",
        "hola usuario"
    )

    memory.add_execution(
        action="create_folder",
        status="success",
        details={
            "folder": "ventas"
        }
    )

    memory.set_preference(
        "theme",
        "dark"
    )

    print(memory.build_context_prompt())

    memory.debug_memory()

