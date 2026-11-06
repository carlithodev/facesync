
"""
======================================================================
MÓDULO: FACESYNC CAPABILITIES — FaceSync AI Tools
Archivo: tools/facesync_tools.py
======================================================================

Responsabilidad:
- Wrapper profesional del motor FaceSync.
- Ejecución segura del reconocimiento facial.
- Gestión de estado de procesos IA.
- Validación de dependencias DeepFace.
- Preparado para agentes IA modernos.

Este módulo NO reemplaza:
✔ facesyncApp/motor_ia.py

Este módulo ACTÚA COMO:
✔ Capa empresarial
✔ Adaptador IA
✔ Tool Calling Layer
✔ Capability Layer

======================================================================
"""

from __future__ import annotations

import os
import csv
import json
import re
import shutil
import time
import threading
import logging
import math
import statistics
import unicodedata
import uuid
import zipfile
import xml.etree.ElementTree as ET

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Iterable, List, Tuple

from core.security import SecurityManager
from core.private_store import protect_text, unprotect_text
from core.identity_registry import (
    IdentityRegistry,
    REGISTRY_SCHEMA as IDENTITY_REGISTRY_SCHEMA,
    file_sha256,
    normalize_reference_code,
)
from core.facesync_storage import (
    SQLITE_STORAGE_SCHEMA,
    SQLiteFaceSyncStore,
    SQLiteIdentityRegistry,
    account_storage_key,
)
from tools.tool_result import tool_error, tool_result

# ============================================================
# IMPORTACIÓN SEGURA DEL MOTOR ORIGINAL
# ============================================================

try:
    from facesyncApp.motor_ia import MotorFaceSync
    MOTOR_AVAILABLE = True
except Exception:
    MOTOR_AVAILABLE = False

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("FaceSync.FaceSyncTools")


class _SimpleTable:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self.columns = list(rows[0].keys()) if rows else []

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row

    def __len__(self):
        return len(self._rows)


class _FaceSyncCancelled(Exception):
    pass

# ============================================================
# CLASE PRINCIPAL
# ============================================================

class FaceSyncCapabilities:
    """
    Capa profesional de capacidades FaceSync.

    Diseñada para:
    - Gemini Tool Calling
    - ChatGPT Function Calling
    - Claude Agents
    - Automatización empresarial
    - Interfaces IA conversacionales

    Características:
    ✔ Ejecución asíncrona
    ✔ Estado persistente
    ✔ Validación de sandbox
    ✔ Wrapper seguro
    ✔ Monitoreo de tareas
    """

    # Formatos RAW admitidos por el clasificador. Mantener esta lista como la
    # unica fuente de verdad evita que un formato sea escaneado pero se pierda
    # despues durante la conversion o el reconocimiento.
    RAW_EXTENSIONS = {".cr2", ".cr3"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"} | RAW_EXTENSIONS
    TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}

    # CR3 is intentionally isolated from the validated CR2 route.  The normal
    # embedded-preview pass remains the first decision.  Only CR3 evidence that
    # is not already secure receives a second, full-RAW half-size pass.  The
    # second representation has its own conversion and embedding cache so
    # pixels/embeddings from the two decode routes can never be mixed.
    CR3_DUAL_DECODE_ENABLED = True
    CR3_PREVIEW_CACHE_VARIANT = "cr3_preview_v1"
    CR3_INDEX_PREVIEW_CACHE_VARIANT = "cr3_index_preview_v1"
    CR3_FULLRAW_CACHE_VARIANT = "cr3_fullraw_v1"
    CR3_FALLBACK_FEEDERS_PER_IDENTITY = 15
    CR3_CROSS_ROUTE_FACE_IOU = 0.25

    # ==============================================================
    # PRECISION THRESHOLDS (cosine distance, ArcFace + RetinaFace)
    # ==============================================================
    # These reproduce the client-validated original engine
    # (FaceSync/tools/facesync_tools.py). ArcFace cosine distance for the SAME
    # person sits ~0.10-0.35; DIFFERENT people sit ~0.45-1.0. DeepFace's
    # verify default (0.68) only balances a 50/50 verification benchmark; for a
    # folder-assignment task it mixes identities. Classification is precision
    # first: a face is only assigned when it is unambiguously the same person.
    #   match seguro:   distance <= THRESHOLD_SECURE
    #   zona dudosa:    THRESHOLD_SECURE < distance <= THRESHOLD_REVIEW (rescue)
    #   no match:       distance > THRESHOLD_REVIEW
    THRESHOLD_SECURE = 0.28
    THRESHOLD_REVIEW = 0.40
    IDENTITY_CONFLICT_MARGIN = 0.03  # Two persons matching same face within this margin -> conflict

    # A clean, strong direct match is accepted without gallery corroboration,
    # exactly as the original engine did. Kept equal to THRESHOLD_SECURE so the
    # precision regime has a single boundary (no looser direct tier).
    DIRECT_CORE_THRESHOLD = 0.28
    IDENTITY_GALLERY_MARGIN = 0.04

    # Multi-face reference disambiguation. A face must recur across distinct
    # photos; temporal proximity is only a soft signal and never the sole vote.
    REFERENCE_RECURRENCE_THRESHOLD = 0.40
    REFERENCE_RECURRENCE_MIN_SCORE_MARGIN = 0.35
    REFERENCE_RECURRENCE_MIN_RATIO = 1.15
    REFERENCE_TIME_SCALE_MIN_SECONDS = 60.0
    REFERENCE_SUPPORT_PEER_DISTANCE = 0.40
    REFERENCE_CONTRADICTION_MIN_SUPPORT = 4
    REFERENCE_MIN_COHERENCE_RATIO = 0.60
    REFERENCE_CROSS_IDENTITY_MARGIN = 0.05
    REFERENCE_MIN_FACE_SIDE_PIXELS = 56.0

    # Dynamic Identity Gallery thresholds. The gallery only operates inside the
    # review zone (THRESHOLD_SECURE..THRESHOLD_REVIEW); every distance limit here
    # is bound to that precision regime so a gallery vote can never rescue a
    # different-person face. Original: feed only from ultra-secure (<=0.22),
    # rescue supporters within 0.37.
    THRESHOLD_ULTRA_SECURE = 0.22       # Only ultra-secure matches feed the gallery
    GALLERY_FEED_MAX_DISTANCE = 0.22    # Strong direct matches may teach the gallery
    GALLERY_MAX_PER_PERSON = 15         # Max confirmed embeddings per student (was 10)
    GALLERY_DUPLICATE_THRESHOLD = 0.05  # Skip near-duplicate gallery embeddings
    GALLERY_RESCUE_MIN_SUPPORTERS = 2   # Min gallery votes to rescue a dubious match
    GALLERY_RESCUE_MAX_DISTANCE = 0.37  # Hard faces need agreement from multiple examples
    GALLERY_RESCUE_MAX_AVG = 0.40       # Consensus must also be collectively plausible
    GALLERY_RESCUE_FEED_MAX_DISTANCE = 0.37
    GALLERY_RESCUE_FEED_MAX_ROBUST_SCORE = 0.40
    GALLERY_STRONG_SUPPORTERS = 3       # Purely visual consensus
    GALLERY_TWO_VOTE_MAX_TIME_DELTA = 120.0  # Two votes need temporal corroboration
    GALLERY_BOOTSTRAP_MAX_DISTANCE = 0.40
    GALLERY_BOOTSTRAP_PEER_DISTANCE = 0.40
    GALLERY_BOOTSTRAP_MIN_IDENTITY_MARGIN = 0.05
    GALLERY_BOOTSTRAP_MAX_TIME_DELTA = 30.0
    GALLERY_BOOTSTRAP_STRONG_VISUAL_EDGE = 0.40
    GALLERY_ADAPTIVE_RADIUS_MIN = 0.37
    GALLERY_ADAPTIVE_RADIUS_MAX = 0.40
    GALLERY_RECOVERY_MIN_PHOTOS = 3
    GALLERY_RECOVERY_PEER_DISTANCE = 0.40
    GALLERY_RECOVERY_MAX_REFERENCE_DISTANCE = 0.40
    GALLERY_RECOVERY_MAX_TIME_DELTA = 300.0

    # Post-motor reference audit.  These limits are intentionally tighter than
    # the review zone: a reference is only considered crossed when its face is
    # clearly closer to another student's numeric neighborhood than to its own
    # coherent neighborhood.  This layer recalculates delivery candidates; it
    # does not change ArcFace, RetinaFace, or the motor thresholds.
    REFERENCE_COLLISION_WINDOW = 8
    REFERENCE_COLLISION_CLUSTER_DISTANCE = 0.28
    REFERENCE_COLLISION_MIN_STEMS = 2
    REFERENCE_COLLISION_MIN_MARGIN = 0.06
    # A strong reference can be crossed even when the other person's photos
    # are far away numerically (for example, a renamed 2462 file containing
    # the face from the 2405 session).  These limits belong to the post-motor
    # audit only; the recognition thresholds remain untouched.
    REFERENCE_COLLISION_GLOBAL_MIN_STEMS = 3
    REFERENCE_COLLISION_GLOBAL_MAX_DISTANCE = 0.30
    REFERENCE_COLLISION_GLOBAL_MARGIN = 0.08

    # Cross-run identity registry. This is an additive reference pre-audit: it
    # reuses embeddings already produced by ArcFace but never changes ArcFace,
    # RetinaFace, recognition thresholds, or final assignment rules.
    HISTORICAL_IDENTITY_MAX_ANCHORS = 5
    HISTORICAL_IDENTITY_MIN_SUPPORT = 2
    HISTORICAL_IDENTITY_SINGLE_ANCHOR_MAX_DISTANCE = THRESHOLD_ULTRA_SECURE
    HISTORICAL_IDENTITY_MULTI_ANCHOR_MAX_DISTANCE = THRESHOLD_SECURE
    HISTORICAL_IDENTITY_MIN_ANCHOR_VOTES = 2

    # Post-motor audit only: weak references are not auto-assigned. This reports
    # coherent orphan portrait groups near a reference that got no visual support.
    WEAK_REFERENCE_ORPHAN_WINDOW = 8
    WEAK_REFERENCE_ORPHAN_MAX_DISTANCE = 0.28
    WEAK_REFERENCE_ORPHAN_MIN_STEMS = 2

    # Large-RAW facial index. The preview pass is deliberately broad; exact
    # classification still belongs to the full patched motor.
    FAST_INDEX_MIN_IMAGES = 500
    FAST_INDEX_MIN_CR2_RATIO = 0.50
    # Garantía + velocidad: el colchón se amplía para que NINGÚN alumno se pierda
    # (entra toda cara con cualquier parecido a una referencia, aunque su preview
    # CR2 salga malo). Solo se descartan caras claramente ajenas (desconocidos).
    # El ahorro se mantiene (lo obviamente ajeno no llega al motor completo).
    FAST_INDEX_CANDIDATE_DISTANCE = 1.10
    FAST_INDEX_TOP_PER_IDENTITY = 500
    FAST_INDEX_NEIGHBOR_RADIUS = 5

    # Folders generated by FaceSync that must be excluded from image scanning
    _FACESYNC_EXCLUDE_DIRS = {
        "pendientes", "_pendientes_revision", "conflictos_identidad",
    }

    # Rescate de pendientes/conflictos (capa POST-decisión, NO toca el motor):
    # en vez de apartar una foto dudosa/en conflicto a "Pendientes", se entrega a
    # la carpeta del MEJOR candidato que el propio motor ya calculó (menor
    # distancia). El motor, sus umbrales y su decisión NO cambian; solo cambia el
    # destino físico de la foto, y se reporta con transparencia.
    # No image is left in a generated Pendientes folder by default.  Review and
    # identity-conflict candidates are delivered to the motor's best candidate
    # and remain fully traceable in the report as forced assignments.
    PENDING_RESCUE_ENABLED = True

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        workspace_path: str,
        security_manager: Optional[SecurityManager] = None,
        account_id: str = "default",
    ):
        """
        Inicializa capacidades FaceSync.

        Args:
            workspace_path:
                Ruta base segura del workspace.

            security_manager:
                Motor de seguridad compartido.
        """

        self.workspace_path = Path(workspace_path).resolve()

        self.security = security_manager or SecurityManager(workspace_path=str(self.workspace_path))
        if Path(getattr(self.security, "workspace_path", self.workspace_path)).resolve() != self.workspace_path:
            self.security = SecurityManager(
                workspace_path=str(self.workspace_path),
                app_data_root=getattr(self.security, "app_data_path", None),
            )

        # ====================================================
        # ESTADO INTERNO
        # ====================================================

        self.current_task = None
        self._cancel_event = threading.Event()
        self._gpu_backend = None
        self._performance_stats: Dict[str, Any] = {}
        self._cr2_prefetch_executor = None
        self._cr2_prefetch_futures: Dict[Path, Any] = {}
        self._delivery_stats = {
            "hardlinks": 0,
            "physical_copies": 0,
            "link_fallbacks": 0,
            "raw_twins": 0,
            "cr2_twins": 0,
            "cr3_twins": 0,
        }
        # The in-memory tier is instance-scoped so switching FaceSync accounts
        # can never reuse another account's biometric cache.
        self._embedding_cache: Dict[tuple, Any] = {}
        self._cr3_fullraw_registry_evidence: Optional[Dict[str, Any]] = None
        self.account_id = str(account_id or "default").strip() or "default"
        self._storage: Optional[SQLiteFaceSyncStore] = None
        self._storage_error = ""

        # Legacy global paths are read-only migration sources. New writes are
        # account-scoped in SQLite and in the account CR2 cache directories.
        self._cache_dir: Optional[Path] = None
        _app_data = getattr(self.security, "app_data_path", None)
        _app_root = Path(_app_data) if _app_data else self.workspace_path / ".facesync_data"
        self._legacy_cache_dir = _app_root / "cache" / "embeddings"
        self._legacy_cr2_cache_dir = _app_root / "cache" / "cr2"
        self._legacy_cr2_preview_cache_dir = _app_root / "cache" / "cr2_preview"
        self._legacy_identity_registry_path = (
            _app_root / "context" / "identity_registry.json"
        )
        # The desktop bridge always supplies the authenticated account.  Keep
        # the historical JSON fallback for internal/CLI callers that do not
        # have an account context; an anonymous "default" process must never
        # claim or mix a real user's biometric history.
        if self.account_id.casefold() != "default":
            try:
                storage = SQLiteFaceSyncStore(
                    _app_root,
                    self.account_id,
                    legacy_identity_path=self._legacy_identity_registry_path,
                    legacy_cache_dir=self._legacy_cache_dir,
                )
                if storage.read_only:
                    self._storage_error = storage.last_error
                    storage.close()
                else:
                    self._storage = storage
            except Exception as exc:
                self._storage_error = f"{type(exc).__name__}: {exc}"

        account_key = account_storage_key(self.account_id)
        if self._storage is not None:
            self._cache_dir = self._storage.cache_root / "embeddings"
            identity_path = self._storage.db_path
        else:
            self._cache_dir = _app_root / "cache" / "accounts" / account_key / "embeddings"
            identity_path = (
                _app_root / "context" / "accounts" / account_key
                / "identity_registry_fallback.json"
            )
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._cache_dir = None

        # Cache de conversiones CR2 -> JPG (RAW no legible por DeepFace).
        self._cr2_cache_dir: Optional[Path] = None
        self._cr2_preview_cache_dir: Optional[Path] = None
        self._cr3_preview_cache_dir: Optional[Path] = None
        self._cr3_fullraw_cache_dir: Optional[Path] = None
        if self._storage is not None:
            self._cr2_cache_dir = self._storage.cr2_cache_dir
            self._cr2_preview_cache_dir = self._storage.cr2_preview_cache_dir
            self._cr3_preview_cache_dir = self._storage.cr3_preview_cache_dir
        elif self._cache_dir:
            self._cr2_cache_dir = self._cache_dir.parent / "cr2"
            self._cr2_preview_cache_dir = self._cache_dir.parent / "cr2_preview"
            self._cr3_preview_cache_dir = self._cache_dir.parent / "cr3_preview"
        if (
            self._cr2_cache_dir
            and self._cr2_preview_cache_dir
            and self._cr3_preview_cache_dir
        ):
            try:
                self._cr2_cache_dir.mkdir(parents=True, exist_ok=True)
                self._cr2_preview_cache_dir.mkdir(parents=True, exist_ok=True)
                self._cr3_preview_cache_dir.mkdir(parents=True, exist_ok=True)
                # Separate from the existing CR2/fast RAW cache by design.  A
                # full CR3 decode must never overwrite or impersonate the
                # validated first-pass representation.
                self._cr3_fullraw_cache_dir = (
                    self._cr2_cache_dir.parent / "cr3_fullraw"
                )
                self._cr3_fullraw_cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._cr2_cache_dir = None
                self._cr2_preview_cache_dir = None
                self._cr3_preview_cache_dir = None
                self._cr3_fullraw_cache_dir = None
        # The labeled registry lives in the account database, outside the
        # disposable cache tree. The JSON path is only an isolated fallback.
        self._identity_registry_path: Optional[Path] = identity_path

        self.status = {
            "running": False,
            "progress": 0,
            "message": "Idle",
            "started_at": None,
            "finished_at": None,
            "last_error": None
        }

    def set_project_root(self, project_root: str):
        self.workspace_path = Path(project_root).resolve()
        if hasattr(self.security, "set_project_root"):
            self.security.set_project_root(str(self.workspace_path))
        else:
            self.security = SecurityManager(workspace_path=str(self.workspace_path))

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    def _enable_gpu_backend(self, model_name: str, detector_backend: str) -> Dict[str, Any]:
        """Enable the verified ONNX forward pass without touching classification."""
        mode = os.environ.get("FACESYNC_ACCELERATOR", "auto").strip().lower()
        stats = {
            "requested": mode,
            "backend": "deepface_tensorflow",
            "gpu_active": False,
            "gpu_fallbacks": 0,
        }
        if mode in {"off", "cpu", "tensorflow"}:
            self._performance_stats.update(stats)
            return stats
        if model_name.lower() != "arcface" or detector_backend.lower() != "retinaface":
            stats["reason"] = "GPU acceleration only supports ArcFace + RetinaFace."
            self._performance_stats.update(stats)
            return stats
        try:
            from facesyncApp.motor_ia_v3 import install_gpu_backend
            self._gpu_backend = install_gpu_backend()
            stats.update({
                "backend": "onnx_directml",
                "gpu_active": True,
                "provider": self._gpu_backend.provider,
            })
        except Exception as exc:
            stats["reason"] = str(exc)
            self._gpu_backend = None
        self._performance_stats.update(stats)
        return stats

    def _disable_gpu_backend(self) -> None:
        backend = self._gpu_backend
        self._gpu_backend = None
        if backend is not None:
            try:
                backend.restore()
            except Exception:
                logger.exception("No se pudo restaurar el backend DeepFace original")
        if self._performance_stats.get("gpu_active"):
            self._performance_stats["gpu_active"] = False

    def _start_cr2_prefetch(self, image_paths: List[Path]) -> None:
        """Decode RAWs ahead of the single deterministic inference consumer."""
        self._stop_cr2_prefetch(wait=False)
        try:
            workers = int(os.environ.get("FACESYNC_CR2_WORKERS", "2"))
        except ValueError:
            workers = 2
        workers = max(1, min(4, workers))
        pending = []
        for image_path in image_paths:
            if image_path.suffix.lower() not in self.RAW_EXTENSIONS:
                continue
            output = self._cr2_cache_path(image_path)
            if output is None or not output.exists() or output.stat().st_size <= 0:
                pending.append(image_path)
        if not pending:
            self._performance_stats["cr2_prefetch_workers"] = 0
            self._performance_stats["cr2_prefetch_count"] = 0
            return
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="facesync-cr2")
        self._cr2_prefetch_executor = executor
        self._cr2_prefetch_futures = {
            path.resolve(strict=False): executor.submit(self._cr2_to_jpeg, path)
            for path in pending
        }
        self._performance_stats["cr2_prefetch_workers"] = workers
        self._performance_stats["cr2_prefetch_count"] = len(pending)

    @staticmethod
    def _record_raw_status(
        metrics: Optional[Dict[str, int]],
        image_path: Path,
        status: str,
        *,
        prefetch: bool = False,
    ) -> None:
        """Registra RAW total y por formato sin mezclar CR2 con CR3."""
        if metrics is None:
            return
        format_name = image_path.suffix.lower().lstrip(".")
        if format_name not in {"cr2", "cr3"}:
            return
        suffix = {
            "converted": "prefetch_convertidas" if prefetch else "convertidas",
            "cache_hit": "prefetch_cache_hits" if prefetch else "cache_hits",
            "dependency": "ignoradas_por_dependencia",
            "error": "errores",
        }.get(status)
        if suffix is None:
            return
        for prefix in ("raw", format_name):
            key = f"{prefix}_{suffix}"
            metrics[key] = metrics.get(key, 0) + 1

    def _await_cr2_prefetch(self, image_path: Path, metrics: Dict[str, int]) -> None:
        future = self._cr2_prefetch_futures.pop(image_path.resolve(strict=False), None)
        if future is None:
            return
        try:
            _converted, status = future.result()
            self._record_raw_status(
                metrics, image_path, status, prefetch=True
            )
        except Exception:
            self._record_raw_status(metrics, image_path, "error", prefetch=True)

    def _stop_cr2_prefetch(self, *, wait: bool) -> None:
        executor = self._cr2_prefetch_executor
        self._cr2_prefetch_executor = None
        self._cr2_prefetch_futures = {}
        if executor is not None:
            try:
                executor.shutdown(wait=wait, cancel_futures=not wait)
            except Exception:
                pass

    # ========================================================
    # SEGURIDAD
    # ========================================================

    def _resolve_secure_path(
        self,
        path: str
    ) -> Path:
        """
        Valida rutas dentro del sandbox.
        """

        secure_path = self.security.secure_path(path)

        if not secure_path:
            raise PermissionError(
                f"Ruta insegura detectada: {path}"
            )

        return Path(secure_path)

    # ========================================================
    # VALIDAR DEPENDENCIAS
    # ========================================================

    def validate_requirements(self) -> Dict[str, Any]:
        """
        Verifica dependencias críticas.

        Returns:
            Dict estructurado.
        """

        result = {
            "success": True,
            "motor_available": MOTOR_AVAILABLE,
            "dependencies": {}
        }

        # ====================================================
        # DEEPFACE
        # ====================================================

        try:
            import deepface
            result["dependencies"]["deepface"] = True
        except Exception:
            result["dependencies"]["deepface"] = False
            result["success"] = False

        # ====================================================
        # PANDAS
        # ====================================================

        try:
            import pandas
            result["dependencies"]["pandas"] = True
        except Exception:
            result["dependencies"]["pandas"] = False
            result["success"] = False

        # ====================================================
        # TENSORFLOW
        # ====================================================

        try:
            import tensorflow
            result["dependencies"]["tensorflow"] = True
        except Exception:
            result["dependencies"]["tensorflow"] = False
            result["success"] = False

        return result

    # ========================================================
    # ESTADO
    # ========================================================

    def get_face_sync_status(self) -> Dict[str, Any]:
        """
        Devuelve el estado actual del motor.

        Returns:
            Dict
        """

        return {
            "success": True,
            "status": self.status
        }

    # ========================================================
    # CALLBACK INTERNO
    # ========================================================

    def _internal_callback(
        self,
        success: bool,
        message: str
    ):
        """
        Callback interno del motor FaceSync.
        """

        self.status["running"] = False
        self.status["finished_at"] = time.time()
        self.status["message"] = message

        if not success:
            self.status["last_error"] = message

        logger.info(f"FaceSync terminó: {message}")

    # ========================================================
    # EJECUTAR MOTOR
    # ========================================================

    def run_face_sync(
        self,
        excel_path: str,
        source_folder: str,
        dest_folder: str,
        name_column: str = "Nombre del Alumno",
        reference_column: str = "Foto",
        callback: str = ''
    ) -> Dict[str, Any]:
        """
        Ejecuta FaceSync en segundo plano.

        Args:
            excel_path:
                Excel con referencias.

            source_folder:
                Carpeta maestra de imágenes.

            dest_folder:
                Carpeta destino.

            name_column:
                Columna del Excel con el nombre del alumno.

            reference_column:
                Columna del Excel con el numero/nombre de referencia de foto.

            callback:
                Callback opcional externo.

        Returns:
            Dict estructurado.
        """

        try:

            # ================================================
            # VALIDAR RUTAS
            # ================================================

            secure_excel = self._resolve_secure_path(
                excel_path
            )

            secure_source = self._resolve_secure_path(
                source_folder
            )

            secure_dest = self._resolve_secure_path(
                dest_folder
            )

            # ================================================
            # EXISTENCIA
            # ================================================

            if not secure_excel.exists():
                return {
                    "success": False,
                    "error": (
                        "El Excel no existe."
                    )
                }

            if not secure_source.exists():
                return {
                    "success": False,
                    "error": (
                        "La carpeta origen no existe."
                    )
                }

            secure_dest.mkdir(
                parents=True,
                exist_ok=True
            )

            # ================================================
            # ESTADO
            # ================================================

            self.status = {
                "running": True,
                "progress": 0,
                "message": "Inicializando FaceSync...",
                "started_at": time.time(),
                "finished_at": None,
                "last_error": None
            }

            # ================================================
            # CALLBACK FINAL
            # ================================================

            def final_callback(success, message):

                self._internal_callback(
                    success,
                    message
                )

                if callback and callable(callback):
                    callback(success, message)

            # ================================================
            # EJECUTAR
            # ================================================

            logger.info(
                "Iniciando reconocimiento facial por referencias..."
            )

            def process():
                result = self.run_reference_face_matching(
                    table_path=str(secure_excel),
                    name_column=name_column,
                    reference_column=reference_column,
                    source_folder=str(secure_source),
                    destination_folder=str(secure_dest),
                )
                if result.get("success"):
                    final_callback(True, "Clasificacion facial completada con exito.")
                else:
                    final_callback(False, result.get("error", "No pude completar FaceSync."))

            threading.Thread(target=process, daemon=True).start()

            return {
                "success": True,
                "message": (
                    "FaceSync iniciado correctamente en modo reference_face_matching."
                ),
                "task_status": self.status,
                "name_column": name_column,
                "reference_column": reference_column,
                "mode": "reference_face_matching",
            }

        except Exception as e:

            logger.exception(
                "Error ejecutando FaceSync"
            )

            self.status["running"] = False
            self.status["last_error"] = str(e)

            return {
                "success": False,
                "error": str(e)
            }

    def run_reference_face_matching(
        self,
        table_path: str,
        name_column: str,
        reference_column: str,
        source_folder: str,
        destination_folder: str,
        *,
        mock_face_matches: Optional[Dict[str, List[str]]] = None,
        threshold: float = 0.40,  # vestigial; real candidate cut is THRESHOLD_REVIEW
        model_name: str = "ArcFace",
        detector_backend: str = "retinaface",
        ambiguity_margin: float = 0.03,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        batch_size: int = 25,
    ) -> Dict[str, Any]:
        """
        Clasifica una carpeta maestra usando una foto de referencia por persona.

        La columna de referencia no es una foto unica a copiar: se usa como rostro
        base para buscar coincidencias contra todas las imagenes de source_folder.
        """

        started = time.time()
        report: Dict[str, Any] = {
            "success": False,
            "action": "run_reference_face_matching",
            "message": "",
            "created": [],
            "reused": [],
            "skipped": [],
            "moved": [],
            "copied": [],
            "deleted": [],
            "errors": [],
            "conflicts": [],
            "report_path": "",
            "metadata": {},
            "mode": "reference_face_matching",
            "total_personas": 0,
            "total_referencias": 0,
            "referencias_encontradas": 0,
            "referencias_faltantes": [],
            "referencias_invalidas": [],
            "seleccion_rostros_referencia": [],
            "seleccion_referencia_cr3": [],
            "preauditoria_referencias": [],
            "referencias_debiles": [],
            "grupos_huerfanos_referencia_debil": [],
            "auditoria_referencias_cruzadas": [],
            "auditoria_referencias_historicas": [],
            "identidades_registradas": [],
            "identity_registry": {
                "enabled": False,
                "schema": IDENTITY_REGISTRY_SCHEMA,
                "codigos_repetidos_historicos": [],
            },
            # SmartReferenceResolver (referencias duplicadas / ambiguas):
            "referencias_resueltas_automaticamente": [],
            "referencias_ambiguas": [],
            "referencias_no_encontradas": [],
            "alumnos_omitidos_por_referencia_dudosa": [],
            "smart_reference": {},
            "total_fotos_analizadas": 0,
            "total_fotos_copiadas": 0,
            "fotos_por_persona": {},
            "fotos_no_identificadas": [],
            "fotos_ignoradas_no_asignadas": [],
            "fotos_dudosas": [],
            "fotos_sin_candidato": [],
            "fotos_multi_alumno": [],
            "conflictos_identidad": [],
            "errores_deepface": [],
            "errores_imagen": [],
            "detalle_asignaciones": [],
            "fotos_rescatadas_galeria": [],
            "fotos_rescatadas_cr3_fullraw": [],
            "arranque_galeria_cr3": [],
            "arbitraje_cr3": [],
            "fotos_rescatadas_pendientes": [],
            "fotos_rescatadas_conflictos": [],
            "fotos_rescatadas_referencia_debil": [],
            "gallery_stats": {},
            "cr2_metrics": {},
            "raw_metrics": {},
            "cr3_dual_decode": {"enabled": False},
            "cr3_reference_selector": {"enabled": False},
            "cr3_gallery_bootstrap": {"enabled": False},
            "cr3_route_arbiter": {"enabled": False},
            "facial_index_stats": {},
            "performance_stats": {},
            "delivery_stats": {},
            "diagnostico": {},
            "source_folder": "",
            "source_folders": [],
            "fotos_por_carpeta_origen": {},
            "destination_folder": "",
            "table_path": "",
            "report_files": {},
            "precision_config": {
                "threshold_ultra_secure": self.THRESHOLD_ULTRA_SECURE,
                "threshold_secure": self.THRESHOLD_SECURE,
                "direct_core_threshold": self.DIRECT_CORE_THRESHOLD,
                "threshold_review": self.THRESHOLD_REVIEW,
                "identity_conflict_margin": self.IDENTITY_CONFLICT_MARGIN,
                "gallery_feed_max_distance": self.GALLERY_FEED_MAX_DISTANCE,
                "gallery_max_per_person": self.GALLERY_MAX_PER_PERSON,
                "gallery_rescue_min_supporters": self.GALLERY_RESCUE_MIN_SUPPORTERS,
                "gallery_rescue_max_distance": self.GALLERY_RESCUE_MAX_DISTANCE,
                "gallery_rescue_max_avg": self.GALLERY_RESCUE_MAX_AVG,
                "gallery_strong_supporters": self.GALLERY_STRONG_SUPPORTERS,
                "gallery_two_vote_max_time_delta": self.GALLERY_TWO_VOTE_MAX_TIME_DELTA,
                "gallery_bootstrap_max_distance": self.GALLERY_BOOTSTRAP_MAX_DISTANCE,
                "gallery_bootstrap_max_time_delta": self.GALLERY_BOOTSTRAP_MAX_TIME_DELTA,
                "identity_gallery_margin": self.IDENTITY_GALLERY_MARGIN,
                "reference_min_face_side_pixels": self.REFERENCE_MIN_FACE_SIDE_PIXELS,
                "gallery_recovery_min_photos": self.GALLERY_RECOVERY_MIN_PHOTOS,
                "gallery_recovery_peer_distance": self.GALLERY_RECOVERY_PEER_DISTANCE,
                "reference_collision_window": self.REFERENCE_COLLISION_WINDOW,
                "reference_collision_cluster_distance": self.REFERENCE_COLLISION_CLUSTER_DISTANCE,
                "reference_collision_min_margin": self.REFERENCE_COLLISION_MIN_MARGIN,
                "reference_collision_global_min_stems": self.REFERENCE_COLLISION_GLOBAL_MIN_STEMS,
                "reference_collision_global_max_distance": self.REFERENCE_COLLISION_GLOBAL_MAX_DISTANCE,
                "reference_collision_global_margin": self.REFERENCE_COLLISION_GLOBAL_MARGIN,
                "historical_identity_single_anchor_max_distance": (
                    self.HISTORICAL_IDENTITY_SINGLE_ANCHOR_MAX_DISTANCE
                ),
                "historical_identity_multi_anchor_max_distance": (
                    self.HISTORICAL_IDENTITY_MULTI_ANCHOR_MAX_DISTANCE
                ),
                "historical_identity_min_anchor_votes": (
                    self.HISTORICAL_IDENTITY_MIN_ANCHOR_VOTES
                ),
                "model_name": model_name,
                "detector_backend": detector_backend,
            },
        }

        cancel_event = cancel_event or self._cancel_event
        self._cancel_event = cancel_event
        self._delivery_stats = {
            "hardlinks": 0,
            "physical_copies": 0,
            "link_fallbacks": 0,
            "raw_twins": 0,
            "cr2_twins": 0,
            "cr3_twins": 0,
        }
        self._performance_stats = {}
        self._cr3_fullraw_registry_evidence = None
        batch_size = max(1, int(batch_size or 25))

        def emit(stage: str, current: int, total: int, message: str, **extra):
            percent = int((current / total) * 100) if total else 0
            self.status.update(
                {
                    "running": stage not in {"done", "canceled", "error"},
                    "progress": percent,
                    "message": message,
                    "last_error": None,
                }
            )
            payload = {
                "event": "progress",
                "stage": stage,
                "current": current,
                "total": total,
                "percent": percent,
                "message": message,
                **extra,
            }
            if current == 0 or stage in {"started", "done", "canceled", "error"} or current % batch_size == 0:
                logger.info("[FaceSyncWorker] %s %s/%s %s", stage, current, total, message)
                print(f"[FaceSyncWorker] {stage} {current}/{total} {message}")
            if progress_callback:
                try:
                    progress_callback(payload)
                except Exception:
                    logger.exception("FaceSync progress callback fallo")

        def check_cancel(stage: str, current: int, total: int):
            import time
            time.sleep(0.001)
            if cancel_event.is_set():
                emit("canceled", current, total, "Proceso cancelado por el usuario.")
                raise _FaceSyncCancelled()

        # Progreso aditivo para fases post-matching (copia). Throttle por tiempo
        # para no saturar la UI cuando hay miles de archivos. NO altera lógica.
        _last_copy_emit = [0.0]

        def emit_copy(current: int, total: int, message: str, **extra):
            now = time.monotonic()
            if current <= 1 or current >= total or now - _last_copy_emit[0] >= 0.3:
                _last_copy_emit[0] = now
                emit("copying", current, total, message, **extra)

        secure_destination: Optional[Path] = None
        identity_registry: Optional[Any] = None
        identity_context: Dict[str, Any] = {}
        identity_run_id = str(uuid.uuid4())
        storage_run_started = False
        try:
            cancel_event.clear()
            emit("started", 0, 0, "Inicializando FaceSync...")
            secure_table = self._resolve_secure_path(table_path)
            secure_destination = self._resolve_secure_path(destination_folder)

            # source_folder admite una carpeta (str) o varias (lista): origen combinado.
            raw_sources = source_folder if isinstance(source_folder, (list, tuple)) else [source_folder]
            secure_sources: List[Path] = []
            invalid_sources: List[str] = []
            for _s in raw_sources:
                if not _s:
                    continue
                _sp = self._resolve_secure_path(_s)
                if _sp.exists() and _sp.is_dir() and _sp not in secure_sources:
                    secure_sources.append(_sp)
                elif not (_sp.exists() and _sp.is_dir()):
                    invalid_sources.append(str(_s))

            if secure_table.suffix.lower() not in self.TABLE_EXTENSIONS:
                return {"success": False, "error": "La tabla debe ser .xlsx, .xls o .csv."}
            if not secure_table.exists() or not secure_table.is_file():
                return {"success": False, "error": "El Excel/CSV no existe."}
            if not secure_sources:
                return {"success": False, "error": "La carpeta maestra de fotos no existe."}
            secure_source = secure_sources[0]  # compat: base para resolver referencias

            secure_destination.mkdir(parents=True, exist_ok=True)
            if self._storage is not None:
                try:
                    if not self._storage.reopen():
                        raise RuntimeError(
                            self._storage.last_error or "No se pudo abrir SQLite."
                        )
                    self._storage.start_run(
                        identity_run_id,
                        model_name=model_name,
                        embedding_schema=self._EMBEDDING_CACHE_SCHEMA,
                        context={
                            "table_path": str(secure_table.resolve(strict=False)),
                            "source_folders": [
                                str(path.resolve(strict=False)) for path in secure_sources
                            ],
                            "destination_folder": str(
                                secure_destination.resolve(strict=False)
                            ),
                        },
                    )
                    storage_run_started = True
                except Exception as exc:
                    self._storage_error = f"{type(exc).__name__}: {exc}"
            # "Pendientes" NO se crea por adelantado: con el rescate activo lo
            # normal es que quede vacía; _copy_image_once la crea solo si se usa.
            pending_dir = secure_destination / "Pendientes"

            table_started = time.perf_counter()
            df = self._read_table(secure_table)
            self._performance_stats["table_load_seconds"] = round(
                time.perf_counter() - table_started, 3
            )
            columns = list(df.columns)
            resolved_name_column = self._resolve_column(columns, name_column)
            resolved_reference_column = self._resolve_column(columns, reference_column)
            if not resolved_name_column:
                return {
                    "success": False,
                    "requires_clarification": True,
                    "missing_slot": "name_column",
                    "columns": columns,
                    "question": "Que columna contiene los nombres para crear las carpetas?",
                }
            if not resolved_reference_column:
                return {
                    "success": False,
                    "requires_clarification": True,
                    "missing_slot": "reference_column",
                    "columns": columns,
                    "question": "Que columna contiene la foto o codigo de referencia?",
                }
            if self._norm_text(resolved_name_column) == self._norm_text(resolved_reference_column):
                return tool_error(
                    "run_reference_face_matching",
                    "La columna de nombres y la columna de referencia no pueden ser la misma.",
                    error_type="same_name_and_reference_column",
                )

            # Escaneo combinado de todas las carpetas origen, dedupe por ruta real.
            scan_started = time.perf_counter()
            image_paths: List[Path] = []
            _seen_imgs: set = set()
            fotos_por_carpeta_origen: Dict[str, int] = {}
            for _src in secure_sources:
                _src_rel = self._relative_to_workspace(_src)
                fotos_por_carpeta_origen.setdefault(_src_rel, 0)
                for _p in self._iter_images(_src, exclude_roots=[secure_destination]):
                    _rp = _p.resolve(strict=False)
                    if _rp in _seen_imgs:
                        continue
                    _seen_imgs.add(_rp)
                    image_paths.append(_p)
                    fotos_por_carpeta_origen[_src_rel] += 1
            image_paths.sort(key=lambda path: str(path).lower())
            _fotos_encontradas = len(image_paths)
            cr2_delivery_index = self._build_cr2_delivery_index(image_paths)
            # Optimización CR2: analizar SOLO el JPG cuando hay JPG+CR2 gemelos
            # (misma foto). El CR2 gemelo se copiará junto al JPG si se clasifica.
            image_paths, cr2_twin_of, cr2_omitidos = self._split_cr2_twins(image_paths)
            _raw_twins_omitted = [
                raw_path
                for raw_paths in cr2_twin_of.values()
                for raw_path in raw_paths
            ]
            _cr2_omitidos = sum(
                path.suffix.lower() == ".cr2" for path in _raw_twins_omitted
            )
            _cr3_omitidos = sum(
                path.suffix.lower() == ".cr3" for path in _raw_twins_omitted
            )
            self._performance_stats["scan_seconds"] = round(
                time.perf_counter() - scan_started, 3
            )
            # De cara al CLIENTE se muestra siempre el total NATURAL (las fotos que
            # él escogió); la optimización de CR2 gemelos es interna y queda
            # documentada en fotos_analizadas_reales / cr2_omitidos_por_jpg_gemelo.
            emit("listed_images", 0, _fotos_encontradas,
                 f"Encontradas {_fotos_encontradas} fotos en {len(secure_sources)} carpeta(s).")
            image_by_name = {path.name.lower(): path for path in image_paths}
            report.update(
                {
                    "source_folder": self._relative_to_workspace(secure_source),
                    "source_folders": [self._relative_to_workspace(s) for s in secure_sources],
                    "fotos_por_carpeta_origen": fotos_por_carpeta_origen,
                    "source_folders_invalidas": invalid_sources,
                    "destination_folder": self._relative_to_workspace(secure_destination),
                    "table_path": self._relative_to_workspace(secure_table),
                    "total_fotos_analizadas": _fotos_encontradas,
                    "fotos_encontradas_total": _fotos_encontradas,
                    "fotos_analizadas_reales": len(image_paths),
                    "raw_omitidos_por_jpg_gemelo": cr2_omitidos,
                    "cr2_omitidos_por_jpg_gemelo": _cr2_omitidos,
                    "cr3_omitidos_por_jpg_gemelo": _cr3_omitidos,
                    "raw_gemelos_copiados": 0,
                    "cr2_gemelos_copiados": 0,
                    "cr3_gemelos_copiados": 0,
                    "name_column": str(resolved_name_column),
                    "reference_column": str(resolved_reference_column),
                }
            )

            people = self._build_people(df, resolved_name_column, resolved_reference_column, secure_destination)
            report["total_personas"] = len(people)
            report["total_referencias"] = len(people)

            identity_registry, identity_context = self._attach_identity_history(
                people,
                table_path=secure_table,
                source_folders=secure_sources,
                model_name=model_name,
                run_id=identity_run_id,
            )
            report["identity_registry"] = dict(identity_context.get("summary") or {})

            for person in people:
                person["folder_path"].mkdir(parents=True, exist_ok=True)
                report["fotos_por_persona"][person["display_name"]] = []

            try:
                from core.smart_reference_resolver import SMART_REFERENCE_ENABLED
            except Exception:
                SMART_REFERENCE_ENABLED = False
            reference_resolution_started = time.perf_counter()
            check_cancel("references", 0, len(people))
            if SMART_REFERENCE_ENABLED:
                # Capa aditiva: resuelve referencias duplicadas con scoring; las
                # únicas se comportan igual que antes; las ambiguas se omiten y
                # se reportan (el motor nunca recibe una referencia dudosa).
                reference_hits = self._resolve_references_smart(
                    people, secure_sources, image_paths, image_by_name, report)
            else:
                reference_hits = 0
                for person in people:
                    check_cancel("references", reference_hits, len(people))
                    reference_path = self._resolve_reference_image(
                        person["reference_value"],
                        secure_source,
                        image_paths,
                        image_by_name,
                    )
                    person["reference_path"] = reference_path
                    if reference_path:
                        reference_hits += 1
                    else:
                        report["referencias_faltantes"].append(
                            {
                                "persona": person["display_name"],
                                "referencia": person["reference_value"],
                            }
                        )
            report["referencias_encontradas"] = reference_hits
            self._performance_stats["reference_resolution_seconds"] = round(
                time.perf_counter() - reference_resolution_started, 3
            )

            match_map = self._collect_mock_matches(people, image_paths, image_by_name, mock_face_matches)
            cache_metrics = {"hits": 0, "misses": 0}
            photo_face_embeddings: Dict[Path, List[list]] = {}
            photo_face_details: Dict[Path, List[Dict[str, Any]]] = {}
            gallery_refs: List[Dict[str, Any]] = []
            # Maquillaje de progreso (solo DISPLAY, el motor no se toca): el motor
            # procesa fotos_analizadas_reales, pero el cliente ve el avance sobre
            # su total NATURAL (lo que escogió), para no confundir.
            _progress_for_engine = progress_callback
            if progress_callback is not None and _fotos_encontradas > len(image_paths) > 0:
                _disp_total = _fotos_encontradas
                _disp_scale = _disp_total / float(len(image_paths))

                def _client_progress(ev, _pc=progress_callback, _s=_disp_scale, _t=_disp_total):
                    try:
                        if isinstance(ev, dict) and ev.get("stage") == "comparing" and ev.get("total"):
                            cur = min(_t, int(round((ev.get("current") or 0) * _s)))
                            ev = dict(ev, current=cur, total=_t,
                                      message=f"Procesando fotos {cur}/{_t}...")
                    except Exception:
                        pass
                    _pc(ev)

                _progress_for_engine = _client_progress
            if mock_face_matches is None:
                real_matches, match_errors = self._collect_deepface_matches(
                    people,
                    image_paths,
                    threshold=self.THRESHOLD_REVIEW,
                    model_name=model_name,
                    detector_backend=detector_backend,
                    progress_callback=_progress_for_engine,
                    cancel_event=cancel_event,
                    batch_size=batch_size,
                )
                match_map = real_matches
                report["errores_deepface"].extend(match_errors.get("deepface", []))
                report["errores_imagen"].extend(match_errors.get("imagen", []))
                report["referencias_invalidas"].extend(match_errors.get("referencias_invalidas", []))
                report["seleccion_rostros_referencia"].extend(
                    match_errors.get("seleccion_rostros_referencia", [])
                )
                report["seleccion_referencia_cr3"].extend(
                    match_errors.get("seleccion_referencia_cr3", [])
                )
                report["cr3_reference_selector"] = match_errors.get(
                    "cr3_reference_selector", {"enabled": False}
                )
                report["preauditoria_referencias"].extend(
                    match_errors.get("preauditoria_referencias", [])
                )
                report["auditoria_referencias_historicas"].extend(
                    match_errors.get("auditoria_referencias_historicas", [])
                )
                report["alumnos_omitidos_por_referencia_dudosa"].extend(
                    match_errors.get("referencias_ambiguas_por_rostro", [])
                )
                cache_metrics = match_errors.get("cache_metrics", cache_metrics)
                report["cr2_metrics"] = match_errors.get("cr2_metrics", {})
                report["raw_metrics"] = dict(report["cr2_metrics"])
                report["facial_index_stats"] = match_errors.get("facial_index_stats", {})
                report["performance_stats"] = match_errors.get("performance_stats", {})
                photo_face_embeddings = match_errors.get("photo_face_embeddings", {})
                photo_face_details = match_errors.get("photo_face_details", {})
                gallery_refs = match_errors.get("refs_with_embeddings", [])
                selected_reference_people = {
                    str(ref.get("person", {}).get("display_name", ""))
                    for ref in gallery_refs
                    if ref.get("person")
                }
                report["referencias_encontradas"] = len(selected_reference_people)
                if selected_reference_people:
                    for key in (
                        "referencias_ambiguas",
                        "referencias_no_encontradas",
                        "referencias_faltantes",
                        "alumnos_omitidos_por_referencia_dudosa",
                    ):
                        report[key] = [
                            item for item in (report.get(key) or [])
                            if str(item.get("persona", "")) not in selected_reference_people
                        ]
                resolved_by_preaudit = sum(
                    1 for item in report["preauditoria_referencias"]
                    if int(item.get("candidatos_encontrados", 0)) > 1
                )
                report["total_referencias_resueltas_preauditoria"] = resolved_by_preaudit
                smart_summary = report.get("smart_reference_summary")
                if isinstance(smart_summary, dict):
                    smart_summary["ambiguas"] = len(report.get("referencias_ambiguas") or [])
                    smart_summary["no_encontradas"] = len(
                        report.get("referencias_no_encontradas") or []
                    )
                    smart_summary["resueltas_por_preauditoria_visual"] = resolved_by_preaudit

            # Capa post-motor: una referencia con el cÃ³digo correcto puede ser
            # una foto de otra persona.  Antes de construir la galerÃ­a, auditamos
            # esos cruces contra los grupos numÃ©ricos completos y reparamos solo
            # la evidencia/candidatos de entrega.  El motor no se modifica.
            if gallery_refs and photo_face_embeddings:
                self._audit_reference_collisions(
                    people,
                    gallery_refs,
                    photo_face_embeddings,
                    match_map,
                    report,
                )

            # --- Build Dynamic Identity Gallery ---
            gallery_data, gallery_stats = self._build_identity_gallery(
                gallery_refs, match_map, photo_face_embeddings,
            )
            cr3_bootstrap_details, cr3_bootstrap_preview = (
                self._bootstrap_cr3_gallery_route(
                    route="preview",
                    refs_with_embeddings=gallery_refs,
                    photo_faces=photo_face_details,
                    gallery_data=gallery_data,
                    match_map=match_map,
                )
            )
            report["arranque_galeria_cr3"] = cr3_bootstrap_details
            report["cr3_gallery_bootstrap"] = {
                "enabled": bool(cr3_bootstrap_preview.get("enabled")),
                "preview": cr3_bootstrap_preview,
                "fullraw": {"enabled": False, "route": "fullraw"},
            }
            gallery_stats["total_gallery_entries"] = sum(
                len(gallery.get("embeddings") or [])
                for gallery in gallery_data.values()
            )
            report["gallery_stats"] = gallery_stats

            global_resolution_started = time.perf_counter()
            confirmed, review_items, identity_conflicts, rescue_details = self._resolve_assignments(
                match_map, ambiguity_margin=ambiguity_margin,
                gallery_data=gallery_data,
                photo_face_embeddings=photo_face_embeddings,
            )
            report.setdefault("performance_stats", {})["global_resolution_seconds"] = round(
                time.perf_counter() - global_resolution_started, 3
            )

            # Segunda representacion exclusiva de CR3. Se ejecuta despues de la
            # decision validada y solo puede agregar identidades en rostros que
            # la primera ruta no dejo asegurados. No reemplaza asignaciones, no
            # admite CR2 y reutiliza sin cambios las reglas/umbrales del motor.
            if mock_face_matches is None:
                cr3_additions, cr3_details, cr3_stats = (
                    self._recover_cr3_fullraw_assignments(
                        image_paths=image_paths,
                        refs_with_embeddings=gallery_refs,
                        base_match_map=match_map,
                        base_photo_faces=photo_face_details,
                        base_confirmed=confirmed,
                        base_conflicts=identity_conflicts,
                        base_rescues=rescue_details,
                        model_name=model_name,
                        detector_backend=detector_backend,
                        ambiguity_margin=ambiguity_margin,
                        cancel_event=cancel_event,
                    )
                )
                for image_path, people_to_add in cr3_additions.items():
                    existing_people = confirmed.setdefault(image_path, [])
                    existing_folders = {
                        str(person.get("folder_name"))
                        for person in existing_people
                    }
                    for person in people_to_add:
                        folder = str(person.get("folder_name"))
                        if folder not in existing_folders:
                            existing_people.append(person)
                            existing_folders.add(folder)
                report["fotos_rescatadas_cr3_fullraw"] = cr3_details
                report["arbitraje_cr3"] = cr3_stats.pop(
                    "route_arbiter_details", []
                )
                report["cr3_route_arbiter"] = cr3_stats.get(
                    "route_arbiter", {"enabled": False}
                )
                report["arranque_galeria_cr3"].extend(
                    cr3_stats.pop("gallery_bootstrap_details", [])
                )
                cr3_bootstrap_fullraw = cr3_stats.get(
                    "gallery_bootstrap", {"enabled": False, "route": "fullraw"}
                )
                report["cr3_gallery_bootstrap"]["fullraw"] = (
                    cr3_bootstrap_fullraw
                )
                report["cr3_gallery_bootstrap"]["enabled"] = bool(
                    report["cr3_gallery_bootstrap"].get("enabled")
                    or cr3_bootstrap_fullraw.get("enabled")
                )
                report["cr3_dual_decode"] = cr3_stats

            # Populate rescued-by-gallery report entries
            for rd in rescue_details:
                report["fotos_rescatadas_galeria"].append({
                    "foto": self._relative_to_workspace(rd["image_path"]),
                    "alumno": rd["person_display_name"],
                    "distancia_base": round(rd["distance_base"], 4),
                    "distancia_galeria": round(rd["distance_gallery"], 4),
                    "evidencia_galeria_count": rd["supporter_count"],
                    "promedio_soporte": round(rd.get("supporter_avg", 999), 4),
                    "soporte_temporal": bool(rd.get("temporal_support", False)),
                    "motivo": "rescued_by_gallery",
                })
            gallery_stats["rescues_successful"] = len(rescue_details)
            copied_sources: set[Path] = set()
            assigned_sources: set[Path] = set()
            delivery_started = time.perf_counter()
            total_copy_work = sum(len(persons) for persons in confirmed.values()) + len(review_items) + len(identity_conflicts) + len(image_paths)
            copy_current = 0

            # --- Copy confirmed assignments (multi-person per image allowed) ---
            for image_path, person_list in confirmed.items():
                is_multi = len(person_list) > 1
                for person in person_list:
                    copy_current += 1
                    check_cancel("copying", copy_current, total_copy_work)
                    emit_copy(copy_current, total_copy_work, "Copiando resultados...",
                              copied_count=report["total_fotos_copiadas"],
                              pending_count=len(review_items) + len(identity_conflicts),
                              error_count=len(report["errors"]))
                    copy_result = self._copy_image_once(image_path, person["folder_path"])
                    if copy_result["status"] in {"copied", "reused"}:
                        copied_sources.add(image_path.resolve(strict=False))
                        assigned_sources.add(image_path.resolve(strict=False))
                        rel = self._relative_to_workspace(Path(copy_result["path"]))
                        report["fotos_por_persona"][person["display_name"]].append(rel)
                        report[copy_result["status"]].append(rel)
                        if copy_result["status"] == "copied":
                            report["total_fotos_copiadas"] += 1
                        # Copiar también el CR2 gemelo a la carpeta del alumno (RAW).
                        report["cr2_gemelos_copiados"] += self._copy_cr2_twin(
                            image_path, person["folder_path"], cr2_twin_of, cr2_delivery_index)
                    elif copy_result["status"] == "conflict":
                        copied_sources.add(image_path.resolve(strict=False))
                        report["conflicts"].append(copy_result)
                        report["errors"].append(copy_result["message"])
                    elif copy_result["status"] == "error":
                        copied_sources.add(image_path.resolve(strict=False))
                        report["errors"].append(copy_result["message"])
                if is_multi:
                    report["fotos_multi_alumno"].append({
                        "foto": self._relative_to_workspace(image_path),
                        "alumnos": [p["display_name"] for p in person_list],
                    })

            # --- Dudosas: entregar al MEJOR candidato que el motor ya calculó ---
            # Capa POST-decisión (rescate de pendientes): el motor dejó estas fotos
            # en zona dudosa CON sus candidatos y distancias; en vez de apartarlas a
            # "Pendientes", se entregan a la carpeta del candidato más cercano y se
            # reporta con transparencia. El motor/umbrales NO cambian. Fallback (sin
            # candidatos o rescate apagado): a Pendientes como siempre.
            for item in review_items:
                copy_current += 1
                check_cancel("copying", copy_current, total_copy_work)
                emit_copy(copy_current, total_copy_work, "Copiando resultados...",
                          copied_count=report["total_fotos_copiadas"],
                          pending_count=len(review_items) + len(identity_conflicts),
                          error_count=len(report["errors"]))
                image_path = item["image_path"]
                matches = sorted((item.get("matches") or []),
                                 key=lambda e: float(e.get("distance", 999)))
                if image_path in confirmed:
                    report["fotos_dudosas"].append({
                        "foto": self._relative_to_workspace(image_path),
                        "candidatos": [e["person"]["display_name"] for e in matches],
                        "distancias": [round(float(e.get("distance", 999)), 4) for e in matches],
                        "motivo": item.get("reason", "rostro_acompanante_dudoso"),
                        "accion": (
                            "No se duplicó la foto: otro rostro de la imagen ya fue identificado."
                        ),
                        "solo_rostro_acompanante": True,
                    })
                    continue
                if not matches:
                    rel = self._relative_to_workspace(image_path)
                    report["fotos_sin_candidato"].append({
                        "foto": rel,
                        "tipo": "zona_dudosa",
                        "accion": (
                            "Sin candidato facial disponible; se conservó en el origen "
                            "y se registró como ignorada, sin enviarla a Pendientes."
                        ),
                    })
                    report["fotos_dudosas"].append({
                        "foto": rel,
                        "candidatos": [],
                        "distancias": [],
                        "motivo": item.get("reason", "zona_dudosa"),
                        "accion": "Ignorada sin candidato; no se creó Pendientes.",
                        "sin_candidato_ignorada": True,
                    })
                    continue
                assigned_person = None
                target_dir = pending_dir
                if self.PENDING_RESCUE_ENABLED and matches:
                    assigned_person = matches[0]["person"]
                    target_dir = assigned_person["folder_path"]
                copy_result = self._copy_image_once(image_path, target_dir)
                if copy_result["status"] in {"copied", "reused"}:
                    copied_sources.add(image_path.resolve(strict=False))
                    rel = self._relative_to_workspace(Path(copy_result["path"]))
                    report[copy_result["status"]].append(rel)
                    if assigned_person is not None:
                        assigned_sources.add(image_path.resolve(strict=False))
                        report["fotos_por_persona"][assigned_person["display_name"]].append(rel)
                        if copy_result["status"] == "copied":
                            report["total_fotos_copiadas"] += 1
                        report["fotos_rescatadas_pendientes"].append({
                            "foto": self._relative_to_workspace(image_path),
                            "alumno": assigned_person["display_name"],
                            "distancia": round(float(matches[0].get("distance", 999)), 4),
                            "candidatos": [e["person"]["display_name"] for e in matches],
                            "motivo": "rescate_de_pendientes (mejor coincidencia del motor)",
                        })
                    # Copiar también el CR2 gemelo al mismo destino (RAW).
                    report["cr2_gemelos_copiados"] += self._copy_cr2_twin(
                        image_path, target_dir, cr2_twin_of, cr2_delivery_index)
                elif copy_result["status"] == "conflict":
                    copied_sources.add(image_path.resolve(strict=False))
                    report["conflicts"].append(copy_result)
                    report["errors"].append(copy_result["message"])
                elif copy_result["status"] == "error":
                    copied_sources.add(image_path.resolve(strict=False))
                    report["errors"].append(copy_result["message"])
                entry = {
                    "foto": self._relative_to_workspace(image_path),
                    "candidatos": [e["person"]["display_name"] for e in matches],
                    "distancias": [round(float(e.get("distance", 999)), 4) for e in matches],
                    "motivo": item.get("reason", "zona_dudosa"),
                }
                if assigned_person is not None:
                    entry["asignada_a"] = assigned_person["display_name"]
                    entry["accion"] = "entregada a su mejor coincidencia (rescate de pendientes)"
                report["fotos_dudosas"].append(entry)

            # --- Conflictos de identidad: entregar al candidato MÁS CERCANO ---
            # Capa POST-decisión: el motor detectó dos candidatos muy parejos; se
            # entrega al de menor distancia (el mejor según el propio motor) y se
            # reporta con ambos scores. Fallback: a revisión como siempre.
            conflict_dir = secure_destination / "_Pendientes_Revision" / "Conflictos_Identidad"
            for item in identity_conflicts:
                copy_current += 1
                check_cancel("copying", copy_current, total_copy_work)
                emit_copy(copy_current, total_copy_work, "Copiando resultados...",
                          copied_count=report["total_fotos_copiadas"],
                          pending_count=len(review_items) + len(identity_conflicts),
                          error_count=len(report["errors"]))
                image_path = item["image_path"]
                candidates = sorted((item.get("candidates") or []),
                                    key=lambda e: float(e.get("distance", 999)))
                if image_path in confirmed:
                    report["conflictos_identidad"].append({
                        "foto": self._relative_to_workspace(image_path),
                        "candidato_1": candidates[0]["person"]["display_name"] if candidates else "",
                        "candidato_2": candidates[1]["person"]["display_name"] if len(candidates) > 1 else "",
                        "score_1": round(float(candidates[0].get("distance", 999)), 4) if candidates else 999,
                        "score_2": round(float(candidates[1].get("distance", 999)), 4) if len(candidates) > 1 else 999,
                        "motivo": "Rostro acompañante ambiguo en una foto ya clasificada.",
                        "accion": (
                            "No se duplicó la foto en conflictos porque otro rostro ya fue identificado."
                        ),
                        "solo_rostro_acompanante": True,
                    })
                    continue
                if not candidates:
                    rel = self._relative_to_workspace(image_path)
                    report["fotos_sin_candidato"].append({
                        "foto": rel,
                        "tipo": "conflicto_identidad",
                        "accion": (
                            "Conflicto sin candidato facial disponible; se conservó "
                            "en el origen y no se creó Pendientes."
                        ),
                    })
                    report["conflictos_identidad"].append({
                        "foto": rel,
                        "candidato_1": "",
                        "candidato_2": "",
                        "score_1": 999,
                        "score_2": 999,
                        "motivo": "Conflicto sin candidatos disponibles.",
                        "accion": "Ignorada sin candidato; no se creó Pendientes.",
                        "sin_candidato_ignorada": True,
                    })
                    continue
                assigned_person = None
                if self.PENDING_RESCUE_ENABLED and candidates:
                    assigned_person = candidates[0]["person"]
                    target_dir = assigned_person["folder_path"]
                else:
                    target_dir = conflict_dir if not mock_face_matches else pending_dir
                copy_result = self._copy_image_once(image_path, target_dir)
                if copy_result["status"] in {"copied", "reused"}:
                    copied_sources.add(image_path.resolve(strict=False))
                    rel = self._relative_to_workspace(Path(copy_result["path"]))
                    report[copy_result["status"]].append(rel)
                    if assigned_person is not None:
                        assigned_sources.add(image_path.resolve(strict=False))
                        report["fotos_por_persona"][assigned_person["display_name"]].append(rel)
                        if copy_result["status"] == "copied":
                            report["total_fotos_copiadas"] += 1
                        report["fotos_rescatadas_conflictos"].append({
                            "foto": self._relative_to_workspace(image_path),
                            "alumno": assigned_person["display_name"],
                            "distancia": round(float(candidates[0].get("distance", 999)), 4),
                            "candidatos": [e["person"]["display_name"] for e in candidates],
                            "motivo": "rescate_de_conflicto (candidato más cercano del motor)",
                        })
                    # Copiar también el CR2 gemelo al mismo destino (RAW).
                    report["cr2_gemelos_copiados"] += self._copy_cr2_twin(
                        image_path, target_dir, cr2_twin_of, cr2_delivery_index)
                elif copy_result["status"] == "conflict":
                    copied_sources.add(image_path.resolve(strict=False))
                entry = {
                    "foto": self._relative_to_workspace(image_path),
                    "candidato_1": candidates[0]["person"]["display_name"] if candidates else "",
                    "candidato_2": candidates[1]["person"]["display_name"] if len(candidates) > 1 else "",
                    "score_1": round(float(candidates[0].get("distance", 999)), 4) if candidates else 999,
                    "score_2": round(float(candidates[1].get("distance", 999)), 4) if len(candidates) > 1 else 999,
                    "motivo": "Scores demasiado cercanos entre dos alumnos para el mismo rostro.",
                }
                if assigned_person is not None:
                    entry["asignada_a"] = assigned_person["display_name"]
                    entry["accion"] = "entregada al candidato más cercano (rescate de conflicto)"
                report["conflictos_identidad"].append(entry)

            # --- Unidentified photos: register as ignored, do NOT copy to Pendientes ---
            # Photos with no relevant match against the current Excel are likely
            # from another classroom.  They stay in the source folder and are
            # recorded in the report so the user can review the numbers.
            for image_path in image_paths:
                copy_current += 1
                check_cancel("copying", copy_current, total_copy_work)
                emit_copy(copy_current, total_copy_work, "Clasificando resultados...",
                          copied_count=report["total_fotos_copiadas"],
                          pending_count=len(review_items) + len(identity_conflicts),
                          error_count=len(report["errors"]))
                resolved = image_path.resolve(strict=False)
                if resolved in copied_sources:
                    continue
                # Do NOT copy — just register as ignored/unassigned
                rel = self._relative_to_workspace(image_path)
                report["fotos_no_identificadas"].append(rel)
                report["fotos_ignoradas_no_asignadas"].append(rel)

            weak_refs, orphan_groups = self._detect_weak_reference_orphan_groups(
                people, image_paths, copied_sources, photo_face_embeddings, report)
            report["referencias_debiles"] = weak_refs
            report["grupos_huerfanos_referencia_debil"] = orphan_groups
            self._deliver_weak_reference_orphan_groups(
                people,
                image_paths,
                orphan_groups,
                copied_sources,
                assigned_sources,
                report,
                cr2_twin_of,
                cr2_delivery_index,
            )

            report.setdefault("performance_stats", {})["delivery_seconds"] = round(
                time.perf_counter() - delivery_started, 3
            )
            report["performance_stats"]["total_pipeline_seconds"] = round(
                time.perf_counter() - table_started, 3
            )
            report["tiempo_total"] = round(time.time() - started, 3)
            report["success"] = True
            registry_summary = report.setdefault("identity_registry", {})
            if identity_registry is not None and registry_summary.get("enabled"):
                confirmed_records = self._build_confirmed_identity_records(
                    gallery_refs,
                    gallery_data,
                    identity_context=identity_context,
                    model_name=model_name,
                )
                fullraw_evidence = self._cr3_fullraw_registry_evidence or {}
                confirmed_records.extend(
                    self._build_confirmed_identity_records(
                        list(fullraw_evidence.get("refs") or []),
                        dict(fullraw_evidence.get("gallery") or {}),
                        identity_context=identity_context,
                        model_name=model_name,
                        representation="fullraw",
                        processing_version=self.CR3_FULLRAW_CACHE_VARIANT,
                        require_gallery_support=True,
                    )
                )
                registry_result = identity_registry.register_many(
                    confirmed_records,
                    run_id=identity_run_id,
                )
                registry_summary.update({
                    "commit_success": bool(registry_result.get("success")),
                    "registered": int(registry_result.get("registered", 0) or 0),
                    "superseded": int(registry_result.get("superseded", 0) or 0),
                    "revision": int(registry_result.get("revision", 0) or 0),
                })
                if registry_result.get("error"):
                    registry_summary["error"] = registry_result["error"]
                if registry_result.get("success"):
                    registry_summary["active_records_after"] = len(
                        identity_registry.active_records()
                    )
                report["identidades_registradas"] = list(
                    registry_result.get("records") or []
                )
            # Archivos ÚTILES entregados al cliente = clasificados + sus CR2 gemelos.
            # (Los CR2 omitidos del ANÁLISIS NO se pierden: se entregan como gemelos.)
            report["raw_gemelos_copiados"] = int(
                self._delivery_stats.get("raw_twins", 0)
            )
            report["cr2_gemelos_copiados"] = int(
                self._delivery_stats.get("cr2_twins", 0)
            )
            report["cr3_gemelos_copiados"] = int(
                self._delivery_stats.get("cr3_twins", 0)
            )
            report["archivos_entregados_totales"] = (
                report.get("total_fotos_copiadas", 0)
                + report.get("raw_gemelos_copiados", 0)
            )
            report["total_fotos_unicas_clasificadas"] = len(assigned_sources)
            report["delivery_stats"] = dict(self._delivery_stats)
            # Attach cache performance metrics
            total_cache_ops = cache_metrics["hits"] + cache_metrics["misses"]
            report["cache_metrics"] = {
                "embeddings_calculados": cache_metrics["misses"],
                "embeddings_reutilizados": cache_metrics["hits"],
                "cache_hits": cache_metrics["hits"],
                "cache_misses": cache_metrics["misses"],
                "cache_hit_percent": round((cache_metrics["hits"] / max(1, total_cache_ops)) * 100, 1),
                "storage": (
                    self._storage.backend
                    if self._storage is not None
                    else "local_encrypted_json_fallback"
                ),
                "account_scope": (
                    self._storage.account_key if self._storage is not None else ""
                ),
                "persistent_entries": (
                    self._storage.cache_count() if self._storage is not None else 0
                ),
            }

            # --- Diagnostic metrics (mixed-classroom awareness) ---
            # De cara al cliente: total NATURAL (lo que escogió) y porcentaje sobre
            # ARCHIVOS ENTREGADOS (clasificados + CR2 gemelos), coherente con lo
            # que ve en sus carpetas.
            total_fotos_origen = _fotos_encontradas
            total_alumnos_excel = len(people)
            total_clasificadas = report["total_fotos_copiadas"]
            total_clasificadas_unicas = len(assigned_sources)
            total_entregadas = report.get("archivos_entregados_totales", total_clasificadas)
            total_rescatadas = len(report.get("fotos_rescatadas_galeria") or [])
            total_rescatadas_cr3_fullraw = len(
                report.get("fotos_rescatadas_cr3_fullraw") or []
            )
            total_resc_pend = len(report.get("fotos_rescatadas_pendientes") or [])
            total_resc_conf = len(report.get("fotos_rescatadas_conflictos") or [])
            total_resc_ref_debil = len(report.get("fotos_rescatadas_referencia_debil") or [])
            total_ref_collisions = len(report.get("auditoria_referencias_cruzadas") or [])
            historical_audits = report.get("auditoria_referencias_historicas") or []
            total_historical_collisions = len(historical_audits)
            total_historical_resolved = sum(
                1 for item in historical_audits if item.get("resuelta")
            )
            total_historical_blocked = sum(
                1 for item in historical_audits if not item.get("resuelta")
            )
            # "Reales" = las que físicamente quedaron apartadas (sin asignar).
            total_pendientes_reales = sum(
                1 for e in (report.get("fotos_dudosas") or [])
                if (
                    not e.get("asignada_a")
                    and not e.get("solo_rostro_acompanante")
                    and not e.get("sin_candidato_ignorada")
                )
            )
            total_conflictos = sum(
                1 for e in (report.get("conflictos_identidad") or [])
                if (
                    not e.get("asignada_a")
                    and not e.get("solo_rostro_acompanante")
                    and not e.get("sin_candidato_ignorada")
                )
            )
            total_huerfanos_pendientes = sum(
                int(group.get("cantidad_archivos_relacionados") or 0)
                for group in (report.get("grupos_huerfanos_referencia_debil") or [])
                if (
                    not group.get("entregado_postmotor")
                    and not group.get("resuelto_por_otro_grupo")
                )
            )
            total_ignoradas = len(report.get("fotos_ignoradas_no_asignadas") or [])
            total_errores_img = len(report.get("errores_imagen") or [])

            fotos_por_persona = report.get("fotos_por_persona", {})
            fotos_counts = [len(v) for v in fotos_por_persona.values()]
            promedio_fotos = round(sum(fotos_counts) / max(1, len(fotos_counts)), 2) if fotos_counts else 0
            alumnos_sin_fotos = [name for name, photos in fotos_por_persona.items() if not photos]
            alumnos_con_pocas = [name for name, photos in fotos_por_persona.items() if 0 < len(photos) <= 2]
            porcentaje_cobertura_origen = round(
                (total_clasificadas_unicas / max(1, total_fotos_origen)) * 100,
                1,
            )
            total_pendiente_entrega = (
                total_pendientes_reales
                + total_conflictos
                + total_huerfanos_pendientes
                + total_errores_img
            )
            porcentaje_entrega = round(
                (total_entregadas / max(1, total_entregadas + total_pendiente_entrega)) * 100,
                1,
            )
            porcentaje_clasificado = porcentaje_cobertura_origen

            diagnostico: Dict[str, Any] = {
                "total_fotos_origen": total_fotos_origen,
                "total_alumnos_excel": total_alumnos_excel,
                "total_clasificadas": total_clasificadas,
                "total_clasificadas_unicas": total_clasificadas_unicas,
                "total_archivos_entregados": total_entregadas,
                "total_rescatadas_por_galeria": total_rescatadas,
                "total_rescatadas_cr3_fullraw": total_rescatadas_cr3_fullraw,
                "total_rescatadas_de_pendientes": total_resc_pend,
                "total_rescatadas_de_conflictos": total_resc_conf,
                "total_rescatadas_referencia_debil": total_resc_ref_debil,
                "total_referencias_cruzadas_reparadas": total_ref_collisions,
                "total_codigos_repetidos_historicos": total_historical_collisions,
                "total_repetidos_historicos_resueltos": total_historical_resolved,
                "total_repetidos_historicos_bloqueados": total_historical_blocked,
                "total_sin_candidato_ignoradas": len(
                    report.get("fotos_sin_candidato") or []
                ),
                "total_pendientes_reales": total_pendientes_reales,
                "total_conflictos_identidad": total_conflictos,
                "total_huerfanos_pendientes": total_huerfanos_pendientes,
                "total_pendiente_entrega": total_pendiente_entrega,
                "total_ignoradas_no_asignadas": total_ignoradas,
                "total_errores_imagen": total_errores_img,
                "porcentaje_clasificado": porcentaje_clasificado,
                "porcentaje_cobertura_origen": porcentaje_cobertura_origen,
                "porcentaje_entrega": porcentaje_entrega,
                "promedio_fotos_por_alumno": promedio_fotos,
                "alumnos_sin_fotos": alumnos_sin_fotos,
                "alumnos_con_pocas_fotos": alumnos_con_pocas,
                "cache_hit_percent": report["cache_metrics"]["cache_hit_percent"],
                "referencias_en_cuarentena": int(
                    report.get("gallery_stats", {}).get("references_quarantined", 0)
                ),
                "referencias_recuperadas_por_cluster": int(
                    report.get("gallery_stats", {}).get("references_recovered_by_cluster", 0)
                ),
                "total_referencias_debiles": len(report.get("referencias_debiles") or []),
                "total_grupos_huerfanos_referencia_debil": len(
                    report.get("grupos_huerfanos_referencia_debil") or []
                ),
                "advertencias": [],
            }

            # Emit warnings for suspicious results
            if total_alumnos_excel > 0 and porcentaje_clasificado < 30 and total_fotos_origen > total_alumnos_excel * 5:
                diagnostico["advertencias"].append(
                    f"Clasificacion baja ({porcentaje_clasificado}%) para {total_fotos_origen} fotos y "
                    f"{total_alumnos_excel} alumnos. Posibles causas: referencias malas, fotos mezcladas "
                    f"de otros salones, umbral estricto, rostros pequenos/borrosos."
                )
            if alumnos_sin_fotos:
                diagnostico["advertencias"].append(
                    f"{len(alumnos_sin_fotos)} alumno(s) sin ninguna foto asignada: {', '.join(alumnos_sin_fotos[:10])}"
                )
            if total_ignoradas > total_clasificadas and total_fotos_origen > 100:
                diagnostico["advertencias"].append(
                    f"Mas fotos ignoradas ({total_ignoradas}) que clasificadas ({total_clasificadas}). "
                    f"Probable mezcla de salones en la carpeta origen."
                )
            unresolved_quarantines = (
                diagnostico["referencias_en_cuarentena"]
                - diagnostico["referencias_recuperadas_por_cluster"]
            )
            if unresolved_quarantines > 0:
                diagnostico["advertencias"].append(
                    f"{unresolved_quarantines} referencia(s) quedaron en cuarentena por baja calidad "
                    "o evidencia contradictoria. Se bloquearon sus asignaciones automáticas para evitar contaminación."
                )

            grupos_huerfanos = report.get("grupos_huerfanos_referencia_debil") or []
            grupos_huerfanos_entregados = [
                group for group in grupos_huerfanos if group.get("entregado_postmotor")
            ]
            grupos_huerfanos_resueltos_por_desempate = [
                group for group in grupos_huerfanos
                if group.get("resuelto_por_otro_grupo")
            ]
            grupos_huerfanos_pendientes = [
                group for group in grupos_huerfanos
                if (
                    not group.get("entregado_postmotor")
                    and not group.get("resuelto_por_otro_grupo")
                )
            ]
            if grupos_huerfanos_entregados:
                diagnostico["advertencias"].append(
                    f"{len(grupos_huerfanos_entregados)} grupo(s) huerfanos de referencia debil "
                    "se entregaron por rescate post-motor. El reconocimiento no se modifico; revisar la hoja "
                    "'Grupos huerfanos' para trazabilidad."
                )
            if grupos_huerfanos_pendientes:
                diagnostico["advertencias"].append(
                    f"{len(grupos_huerfanos_pendientes)} grupo(s) de fotos ignoradas "
                    "parecen coherentes entre si, pero su referencia no tuvo soporte visual. Revisar la hoja "
                    "'Grupos huerfanos' antes de asignarlos manualmente."
                )
            if grupos_huerfanos_resueltos_por_desempate:
                diagnostico["advertencias"].append(
                    f"{len(grupos_huerfanos_resueltos_por_desempate)} grupo(s) huerfanos no se duplicaron "
                    "porque fueron resueltos por desempate global post-motor."
                )
            if total_ref_collisions:
                diagnostico["advertencias"].append(
                    f"{total_ref_collisions} referencia(s) cruzada(s) fueron reparadas "
                    "post-motor con un cluster numérico coherente; revisar la hoja "
                    "'Referencias cruzadas'."
                )
            if total_historical_resolved:
                diagnostico["advertencias"].append(
                    f"{total_historical_resolved} referencia(s) repetida(s) entre salones "
                    "se resolvieron descartando identidades confirmadas del registro local."
                )
            if total_historical_blocked:
                diagnostico["advertencias"].append(
                    f"{total_historical_blocked} referencia(s) no se asignaron porque todos "
                    "sus candidatos pertenecian a identidades confirmadas de salones anteriores."
                )

            report["diagnostico"] = diagnostico

            emit("reporting", len(image_paths), len(image_paths), "Generando reportes...",
                 copied_count=report["total_fotos_copiadas"], error_count=len(report["errors"]))
            report["report_files"] = self._write_reports(report, secure_destination)
            report["report_path"] = report["report_files"].get("json", "")
            report["message"] = "Clasificacion facial completada."
            report["skipped"] = list(report.get("fotos_ignoradas_no_asignadas") or [])
            report["metadata"] = {
                "copied_count": len(report["copied"]),
                "unique_classified_count": total_clasificadas_unicas,
                "reused_count": len(report["reused"]),
                "skipped_count": len(report["skipped"]),
                "pending_count": total_pendientes_reales + total_conflictos,
                "ignored_unassigned_count": total_ignoradas,
                "conflict_count": len(report["conflicts"]),
                "identity_conflict_count": total_conflictos,
                "multi_alumno_count": len(report.get("fotos_multi_alumno") or []),
                "invalid_reference_count": len(report.get("referencias_invalidas") or []),
                "image_error_count": total_errores_img,
                "rescued_by_gallery_count": total_rescatadas,
                "rescued_by_cr3_fullraw_count": total_rescatadas_cr3_fullraw,
                "rescued_by_weak_reference_count": total_resc_ref_debil,
                "reference_collision_repair_count": total_ref_collisions,
                "historical_reference_collision_count": total_historical_collisions,
                "historical_reference_resolved_count": total_historical_resolved,
                "historical_reference_blocked_count": total_historical_blocked,
                "weak_reference_count": len(report.get("referencias_debiles") or []),
                "weak_reference_orphan_group_count": len(
                    report.get("grupos_huerfanos_referencia_debil") or []
                ),
                "gallery_feeds": report.get("gallery_stats", {}).get("gallery_feeds", 0),
                "hardlink_count": report.get("delivery_stats", {}).get("hardlinks", 0),
                "physical_copy_count": report.get("delivery_stats", {}).get("physical_copies", 0),
                "performance_backend": report.get("performance_stats", {}).get("backend", ""),
                "cache_hit_percent": report["cache_metrics"]["cache_hit_percent"],
                "porcentaje_clasificado": porcentaje_clasificado,
                "porcentaje_cobertura_origen": porcentaje_cobertura_origen,
                "porcentaje_entrega": porcentaje_entrega,
                "promedio_fotos_por_alumno": promedio_fotos,
                "table_path": report["table_path"],
                "name_column": report["name_column"],
                "reference_column": report["reference_column"],
                "source_folder": report["source_folder"],
                "destination_folder": report["destination_folder"],
            }
            emit("finalizing", len(image_paths), len(image_paths), "Finalizando...",
                 copied_count=report["total_fotos_copiadas"], error_count=len(report["errors"]))
            emit("done", len(image_paths), len(image_paths), "Clasificacion facial completada.", **report["metadata"])
            return report

        except _FaceSyncCancelled:
            report["tiempo_total"] = round(time.time() - started, 3)
            report["canceled"] = True
            report["success"] = False
            report["message"] = "Clasificacion facial cancelada. Se guardo reporte parcial cuando fue posible."
            report["error"] = "Proceso cancelado por el usuario."
            if secure_destination is not None:
                try:
                    report["report_files"] = self._write_reports(report, secure_destination)
                    report["report_path"] = report["report_files"].get("json", "")
                except Exception:
                    pass
            return report
        except PermissionError as e:
            report["tiempo_total"] = round(time.time() - started, 3)
            report["error"] = str(e)
            return report
        except RuntimeError as e:
            report["tiempo_total"] = round(time.time() - started, 3)
            report["error"] = str(e)
            return report
        except Exception as e:
            logger.exception("Error en run_reference_face_matching")
            report["tiempo_total"] = round(time.time() - started, 3)
            report["error"] = str(e)
            return report
        finally:
            self._stop_cr2_prefetch(wait=False)
            self._disable_gpu_backend()
            if self._storage is not None:
                try:
                    self._storage.flush_cache()
                    if storage_run_started:
                        final_status = (
                            "completed"
                            if report.get("success")
                            else "canceled"
                            if report.get("canceled")
                            else "failed"
                        )
                        self._storage.finish_run(
                            identity_run_id,
                            status=final_status,
                            summary={
                                "success": bool(report.get("success")),
                                "canceled": bool(report.get("canceled")),
                                "error": str(report.get("error") or ""),
                                "total_photos": int(
                                    report.get("total_fotos_analizadas", 0) or 0
                                ),
                                "delivered_files": int(
                                    report.get("archivos_entregados_totales", 0) or 0
                                ),
                                "registered_identities": len(
                                    report.get("identidades_registradas") or []
                                ),
                                "report_path": str(report.get("report_path") or ""),
                                "elapsed_seconds": float(
                                    report.get("tiempo_total", 0) or 0
                                ),
                            },
                        )
                except Exception as exc:
                    self._storage_error = f"{type(exc).__name__}: {exc}"
                finally:
                    self._storage.close()

    def _read_table(self, table_path: Path):
        try:
            import pandas as pd
        except Exception:
            pd = None

        if table_path.suffix.lower() == ".csv":
            if pd is None:
                try:
                    text = table_path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    text = table_path.read_text(encoding="latin-1")
                return _SimpleTable([dict(row) for row in csv.DictReader(text.splitlines())])
            try:
                return pd.read_csv(table_path, dtype=str, encoding="utf-8-sig")
            except UnicodeDecodeError:
                return pd.read_csv(table_path, dtype=str, encoding="latin-1")

        if pd is None:
            if table_path.suffix.lower() == ".xlsx":
                return _SimpleTable(self._read_xlsx_rows(table_path))
            raise RuntimeError("La libreria pandas/xlrd no esta instalada para leer archivos .xls.")
        data = pd.read_excel(table_path, dtype=str, sheet_name=0)
        if isinstance(data, dict):
            return next(iter(data.values()))
        return data

    def _read_xlsx_rows(self, table_path: Path) -> List[Dict[str, Any]]:
        with zipfile.ZipFile(table_path) as archive:
            shared_strings = self._read_xlsx_shared_strings(archive)
            sheet_path = self._first_xlsx_sheet_path(archive)
            with archive.open(sheet_path) as sheet_file:
                root = ET.parse(sheet_file).getroot()

        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        matrix: List[List[str]] = []
        for row in root.findall(".//x:sheetData/x:row", ns):
            values: List[str] = []
            for cell in row.findall("x:c", ns):
                cell_ref = cell.attrib.get("r", "")
                column_index = self._xlsx_column_index(cell_ref)
                while len(values) <= column_index:
                    values.append("")
                values[column_index] = self._xlsx_cell_value(cell, shared_strings)
            matrix.append(values)

        matrix = [row for row in matrix if any(str(value).strip() for value in row)]
        if not matrix:
            return []

        headers = [str(value).strip() or f"Column {index + 1}" for index, value in enumerate(matrix[0])]
        rows: List[Dict[str, Any]] = []
        for raw_row in matrix[1:]:
            row = {}
            for index, header in enumerate(headers):
                row[header] = raw_row[index] if index < len(raw_row) else ""
            if any(str(value).strip() for value in row.values()):
                rows.append(row)
        return rows

    def _read_xlsx_shared_strings(self, archive: zipfile.ZipFile) -> List[str]:
        try:
            with archive.open("xl/sharedStrings.xml") as file:
                root = ET.parse(file).getroot()
        except KeyError:
            return []

        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings: List[str] = []
        for item in root.findall("x:si", ns):
            strings.append("".join(node.text or "" for node in item.findall(".//x:t", ns)))
        return strings

    def _first_xlsx_sheet_path(self, archive: zipfile.ZipFile) -> str:
        try:
            with archive.open("xl/workbook.xml") as workbook_file:
                workbook_root = ET.parse(workbook_file).getroot()
            with archive.open("xl/_rels/workbook.xml.rels") as rels_file:
                rels_root = ET.parse(rels_file).getroot()
        except KeyError:
            return "xl/worksheets/sheet1.xml"

        workbook_ns = {
            "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        rels_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        first_sheet = workbook_root.find(".//x:sheets/x:sheet", workbook_ns)
        if first_sheet is None:
            return "xl/worksheets/sheet1.xml"

        relation_id = first_sheet.attrib.get(f"{{{workbook_ns['r']}}}id")
        for relation in rels_root.findall("rel:Relationship", rels_ns):
            if relation.attrib.get("Id") == relation_id:
                target = relation.attrib.get("Target", "worksheets/sheet1.xml")
                return "xl/" + target.lstrip("/")
        return "xl/worksheets/sheet1.xml"

    def _xlsx_cell_value(self, cell: ET.Element, shared_strings: List[str]) -> str:
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//x:t", ns)).strip()

        value_node = cell.find("x:v", ns)
        value = value_node.text if value_node is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(value)].strip()
            except Exception:
                return ""
        if cell_type == "b":
            return "TRUE" if value == "1" else "FALSE"
        return str(value or "").strip()

    def _xlsx_column_index(self, cell_ref: str) -> int:
        letters = re.match(r"([A-Za-z]+)", str(cell_ref or ""))
        if not letters:
            return 0
        index = 0
        for char in letters.group(1).upper():
            index = index * 26 + (ord(char) - ord("A") + 1)
        return max(0, index - 1)

    def _build_people(self, df, name_column: str, reference_column: str, destination_folder: Path) -> List[Dict[str, Any]]:
        try:
            import pandas as pd
        except Exception:
            pd = None

        people: List[Dict[str, Any]] = []
        seen: Dict[str, int] = {}
        for _, row in df.iterrows():
            raw_name = row.get(name_column)
            raw_reference = row.get(reference_column)
            if pd is not None and (pd.isna(raw_name) or pd.isna(raw_reference)):
                continue
            display_name = re.sub(r"\s+", " ", str(raw_name or "").strip())
            reference_value = self._normalize_reference_value(raw_reference)
            folder_base = self._sanitize_folder_name(display_name)
            if not display_name or not reference_value or not folder_base:
                continue

            count = seen.get(folder_base, 0) + 1
            seen[folder_base] = count
            folder_name = folder_base if count == 1 else f"{folder_base} ({count})"
            people.append(
                {
                    "display_name": display_name,
                    "folder_name": folder_name,
                    "folder_path": destination_folder / folder_name,
                    "reference_value": reference_value,
                }
            )

        return people

    def _attach_identity_history(
        self,
        people: List[Dict[str, Any]],
        *,
        table_path: Path,
        source_folders: List[Path],
        model_name: str,
        run_id: str,
    ) -> Tuple[Optional[Any], Dict[str, Any]]:
        """Attach prior owners only to Excel rows whose code has history.

        Merely loading the registry does not affect normal runs.  The visual
        pre-audit consults ``historical_identity_records`` only when this method
        found a compatible active record for the same numeric code.
        """
        salon = Path(table_path).stem
        context: Dict[str, Any] = {
            "salon": salon,
            "table_path": str(Path(table_path).resolve(strict=False)),
            "table_hash": file_sha256(Path(table_path)),
            "source_folders": [
                str(Path(folder).resolve(strict=False)) for folder in source_folders
            ],
            "run_id": str(run_id),
        }
        summary: Dict[str, Any] = {
            "enabled": False,
            "schema": IDENTITY_REGISTRY_SCHEMA,
            "storage": (
                self._storage.backend
                if self._storage is not None
                else "local_encrypted_json_fallback"
            ),
            "salon": salon,
            "active_records_before": 0,
            "codigos_repetidos_historicos": [],
            "collisions": [],
        }
        if self._storage is not None:
            summary.update({
                "account_scope": self._storage.account_key,
                "database_schema": SQLITE_STORAGE_SCHEMA,
            })
        elif self._storage_error:
            summary["storage_warning"] = self._storage_error
        context["summary"] = summary
        if self._identity_registry_path is None:
            summary["error"] = "No fue posible resolver el almacenamiento privado."
            return None, context

        registry = (
            SQLiteIdentityRegistry(self._storage)
            if self._storage is not None
            else IdentityRegistry(self._identity_registry_path)
        )
        active_records = registry.active_records()
        summary["active_records_before"] = len(active_records)
        if registry.read_only:
            summary["error"] = registry.last_error
            return registry, context

        summary["enabled"] = True
        repeated_codes = set()
        for person in people:
            records = registry.find_historical(
                person.get("reference_value"),
                current_student=str(person.get("display_name", "")),
                current_salon=salon,
                model_name=model_name,
                embedding_schema=self._EMBEDDING_CACHE_SCHEMA,
            )
            person["historical_identity_records"] = records
            if not records:
                continue
            code = normalize_reference_code(person.get("reference_value"))
            repeated_codes.add(code)
            summary["collisions"].append({
                "code": code,
                "current_student": person.get("display_name", ""),
                "current_salon": salon,
                "historical_owners": [
                    IdentityRegistry.public_record(record) for record in records
                ],
            })
        summary["codigos_repetidos_historicos"] = sorted(repeated_codes)
        return registry, context

    def _build_confirmed_identity_records(
        self,
        refs_with_embeddings: List[Dict[str, Any]],
        gallery_data: Dict[str, Dict[str, Any]],
        *,
        identity_context: Dict[str, Any],
        model_name: str,
        representation: str = "",
        processing_version: str = "",
        require_gallery_support: bool = False,
    ) -> List[Dict[str, Any]]:
        """Create route-separated records from trusted, supported references."""
        records: List[Dict[str, Any]] = []
        for ref in refs_with_embeddings or []:
            if not ref.get("reference_trusted", True):
                continue
            person = ref.get("person") or {}
            folder = str(person.get("folder_name", ""))
            gallery = gallery_data.get(folder) or {}
            reference_embedding = ref.get("embedding")
            if not reference_embedding:
                continue
            reference_path = Path(ref.get("path"))
            is_cr3 = reference_path.suffix.lower() == ".cr3"
            if representation and not is_cr3:
                continue

            gallery_paths = [
                Path(path).resolve(strict=False)
                for path in (gallery.get("paths") or [])
            ]
            reference_resolved = reference_path.resolve(strict=False)
            independent_supports = {
                path for path in gallery_paths if path != reference_resolved
            }
            support_count = (
                len(independent_supports)
                if require_gallery_support
                else int(ref.get("reference_coherent_support") or 0)
            )
            if support_count < self.HISTORICAL_IDENTITY_MIN_SUPPORT:
                continue

            anchors: List[list] = []
            anchor_paths: List[str] = []
            gallery_embeddings = list(gallery.get("embeddings") or [])
            candidates = [(reference_embedding, reference_resolved)]
            candidates.extend(
                (
                    embedding,
                    gallery_paths[index]
                    if index < len(gallery_paths)
                    else reference_resolved,
                )
                for index, embedding in enumerate(gallery_embeddings)
            )
            for embedding, anchor_path in candidates:
                if not embedding:
                    continue
                vector = [float(value) for value in embedding]
                if any(
                    self._cosine_distance(vector, existing)
                    < self.GALLERY_DUPLICATE_THRESHOLD
                    for existing in anchors
                ):
                    continue
                anchors.append(vector)
                anchor_paths.append(str(anchor_path))
                if len(anchors) >= self.HISTORICAL_IDENTITY_MAX_ANCHORS:
                    break
            # A root plus at least one independent confirmed view keeps the
            # historical comparison resistant to pose and lighting changes.
            if len(anchors) < 2:
                continue

            coherence_ratio = float(ref.get("reference_coherence_ratio") or 0.0)
            if require_gallery_support and len(anchors) > 1:
                coherence_ratio = sum(
                    self._cosine_distance(anchors[0], anchor)
                    <= self.THRESHOLD_REVIEW
                    for anchor in anchors[1:]
                ) / max(1, len(anchors) - 1)

            record = {
                "code": normalize_reference_code(person.get("reference_value")),
                "student": str(person.get("display_name", "")),
                "salon": str(identity_context.get("salon", "")),
                "table_path": str(identity_context.get("table_path", "")),
                "table_hash": str(identity_context.get("table_hash", "")),
                "source_folders": list(identity_context.get("source_folders") or []),
                "reference_path": str(reference_path.resolve(strict=False)),
                "reference_hash": file_sha256(reference_path),
                "selected_face_index": int(ref.get("selected_face_index", 0) or 0),
                "primary_embedding": [float(value) for value in reference_embedding],
                "embeddings": anchors,
                "anchor_paths": anchor_paths,
                "model_name": str(model_name),
                "embedding_schema": self._EMBEDDING_CACHE_SCHEMA,
                "support_count": support_count,
                "coherence_ratio": round(
                    coherence_ratio, 6
                ),
                "reference_selection_score": round(
                    float(ref.get("reference_selection_score") or 0.0), 6
                ),
                "camera": dict(ref.get("camera") or {}),
                "confidence": "high",
            }
            if is_cr3:
                record.update({
                    "format_family": "cr3",
                    "representation": representation or "preview",
                    "processing_version": (
                        processing_version or self.CR3_PREVIEW_CACHE_VARIANT
                    ),
                })
            records.append(record)
        return records

    def _resolve_column(self, columns: Iterable[Any], requested: str) -> str:
        columns = [str(column) for column in columns]
        if not columns:
            return ""
        requested_norm = self._norm_text(requested)
        normalized_columns = {self._norm_text(column): column for column in columns}
        if requested_norm and requested_norm in normalized_columns:
            return normalized_columns[requested_norm]
        if requested_norm:
            requested_tokens = set(requested_norm.split())
            for norm, original in normalized_columns.items():
                if requested_tokens and requested_tokens.issubset(set(norm.split())):
                    return original
        return ""

    def _iter_images(self, source_folder: Path, *, exclude_roots: Optional[List[Path]] = None) -> List[Path]:
        exclude_roots = [path.resolve(strict=False) for path in (exclude_roots or [])]
        skip_names = {".git", "__pycache__", "env", "venv", "env_ia", "node_modules", ".facesync_cache"}
        skip_names.update(self._FACESYNC_EXCLUDE_DIRS)
        images: List[Path] = []
        for root, dirs, files in os.walk(source_folder):
            root_path = Path(root).resolve(strict=False)
            if any(self._is_relative_to(root_path, excluded) for excluded in exclude_roots):
                dirs[:] = []
                continue
            dirs[:] = [name for name in dirs if name.lower() not in skip_names and not name.startswith("_reporte")]
            # Also skip report files
            for file_name in files:
                if file_name.startswith("_reporte"):
                    continue
                path = Path(root) / file_name
                if path.suffix.lower() in self.IMAGE_EXTENSIONS:
                    images.append(path)
        images.sort(key=lambda path: str(path).lower())
        return images

    def _resolve_reference_image(
        self,
        reference_value: str,
        source_folder: Path,
        image_paths: List[Path],
        image_by_name: Dict[str, Path],
    ) -> Optional[Path]:
        reference = str(reference_value or "").strip().strip('"').strip("'")
        if not reference:
            return None

        secure_reference = self.security.secure_path(reference)
        if secure_reference:
            candidate = Path(secure_reference)
            if candidate.is_file() and candidate.suffix.lower() in self.IMAGE_EXTENSIONS:
                return candidate

        relative_candidate = (source_folder / reference).resolve(strict=False)
        if relative_candidate.is_file() and relative_candidate.suffix.lower() in self.IMAGE_EXTENSIONS:
            return relative_candidate

        if Path(reference).suffix.lower() in self.IMAGE_EXTENSIONS:
            by_name = image_by_name.get(Path(reference).name.lower())
            if by_name:
                return by_name

        stem = Path(reference).stem if Path(reference).suffix else reference
        stem_norm = self._norm_reference_stem(stem)
        for extension in self.IMAGE_EXTENSIONS:
            by_name = image_by_name.get(f"{stem}{extension}".lower())
            if by_name:
                return by_name

        exact_stem_matches = [path for path in image_paths if self._norm_reference_stem(path.stem) == stem_norm]
        if exact_stem_matches:
            return exact_stem_matches[0]

        numeric = re.findall(r"\d+", stem_norm)
        if numeric:
            number = numeric[-1]
            numeric_matches = [path for path in image_paths if re.findall(r"\d+", path.stem) and re.findall(r"\d+", path.stem)[-1] == number]
            if numeric_matches:
                return numeric_matches[0]

        return None

    # ==================================================================
    # SmartReferenceResolver — capa ADITIVA (solo actúa cuando hay duplicados).
    # NO toca el motor: solo decide QUÉ archivo de referencia se le pasa.
    # ==================================================================
    def _ref_folder(self, path: Path) -> str:
        """Carpeta (relativa al workspace) que contiene al archivo candidato."""
        try:
            return self._relative_to_workspace(path.parent)
        except Exception:
            return str(path.parent)

    def _as_ref_candidate(self, path: Path):
        from core.smart_reference_resolver import RefCandidate
        return RefCandidate(path=str(path), folder=self._ref_folder(path),
                            ext=path.suffix.lower())

    def _is_excluded_reference_path(self, path: Path) -> bool:
        """No usar como referencia archivos en carpetas de SALIDA (destino,
        CLASIFICADOS*, Pendientes, conflictos, reportes). Solo carpetas origen."""
        rel = self._relative_to_workspace(path)
        for seg in rel.replace("\\", "/").split("/"):
            low = seg.lower()
            if (low in self._FACESYNC_EXCLUDE_DIRS
                    or low.startswith("clasificados")
                    or low.startswith("_reporte")
                    or low.startswith("_pendientes")):
                return True
        return False

    def _haar_cascade(self):
        """Carga perezosa del clasificador Haar de OpenCV (detector clásico de
        caras). NO es el motor de reconocimiento (DeepFace/RetinaFace/ArcFace);
        solo sirve para elegir la foto de referencia (retrato vs familiar)."""
        c = getattr(self, "_haar_cascade_obj", "unset")
        if c == "unset":
            try:
                import cv2
                c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                if c.empty():
                    c = None
            except Exception:
                c = None
            self._haar_cascade_obj = c
        return c

    def _count_faces_opencv(self, path) -> int:
        """Nº de caras con OpenCV Haar (con corrección EXIF + downscale). Cacheado.
        Devuelve -1 si no se puede calcular. NO toca el motor."""
        key = str(path)
        cache = getattr(self, "_face_count_cache", None)
        if cache is None:
            cache = {}
            self._face_count_cache = cache
        if key in cache:
            return cache[key]
        n = -1
        try:
            import cv2
            import numpy as np
            from PIL import Image, ImageOps
            cascade = self._haar_cascade()
            if cascade is not None:
                im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
                w, h = im.size
                scale = 900.0 / max(w, h, 1)
                if scale < 1:
                    im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
                gray = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
                n = int(len(faces))
        except Exception:
            n = -1
        cache[key] = n
        return n

    def _portrait_fraction(self, paths: List[Path], sample: int = 30) -> float:
        """Fracción de la muestra que es retrato SOLO (exactamente 1 cara). Alto =
        sesión de retratos; bajo = fotos familiares/grupales. OpenCV, no el motor."""
        jpgs = [p for p in paths if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if not jpgs:
            return 0.0
        step = max(1, len(jpgs) // sample)
        sampled = jpgs[::step][:sample]
        ones = total = 0
        for p in sampled:
            n = self._count_faces_opencv(p)
            if n < 0:
                continue
            total += 1
            if n == 1:
                ones += 1
        return (ones / total) if total else 0.0

    def _build_reference_index(self, image_paths: List[Path]) -> Dict[str, List[Path]]:
        """Índice número -> [paths]. Se construye UNA sola vez por lote (no se
        reescanea disco por alumno). Excluye carpetas de salida (no usar
        resultados previos como referencia)."""
        index: Dict[str, List[Path]] = {}
        for p in image_paths:
            if self._is_excluded_reference_path(p):
                continue
            nums = re.findall(r"\d+", self._norm_reference_stem(p.stem))
            if nums:
                index.setdefault(nums[-1], []).append(p)
        return index

    def _group_ref_candidates(self, paths: List[Path]) -> list:
        """1 candidato por carpeta, prefiriendo JPG/PNG sobre CR2 dentro de la
        misma carpeta (caso 'JPG y CR2 juntos' = un solo candidato = referencia
        única). No elimina soporte CR2: solo prefiere JPG si existe."""
        # Only collapse true JPG/CR2 twins. Different stems can contain
        # different people even when the final numeric code and folder match.
        preferred = (".jpg", ".jpeg", ".png")
        by_capture: Dict[Tuple[str, str], Path] = {}
        for p in paths:
            key = (
                str(p.parent.resolve(strict=False)).lower(),
                self._norm_reference_stem(p.stem),
            )
            cur = by_capture.get(key)
            if cur is None:
                by_capture[key] = p
            elif p.suffix.lower() in preferred and cur.suffix.lower() not in preferred:
                by_capture[key] = p
        return [
            self._as_ref_candidate(path)
            for path in sorted(by_capture.values(), key=lambda item: str(item).lower())
        ]

    def _reference_candidates(self, reference_value: str, source_folder: Path,
                              image_paths: List[Path], image_by_name: Dict[str, Path],
                              ref_index: Dict[str, List[Path]]) -> list:
        """Lista de candidatos (agrupada por carpeta). Los casos EXACTOS (ruta
        segura / relativa / nombre con extensión) devuelven 1 candidato; el caso
        típico de número suelto consulta el índice."""
        ref = str(reference_value or "").strip().strip('"').strip("'")
        if not ref:
            return []
        secure_reference = self.security.secure_path(ref)
        if secure_reference:
            cand = Path(secure_reference)
            if cand.is_file() and cand.suffix.lower() in self.IMAGE_EXTENSIONS:
                return [self._as_ref_candidate(cand)]
        rel = (source_folder / ref).resolve(strict=False)
        if rel.is_file() and rel.suffix.lower() in self.IMAGE_EXTENSIONS:
            return [self._as_ref_candidate(rel)]
        if Path(ref).suffix.lower() in self.IMAGE_EXTENSIONS:
            by_name = image_by_name.get(Path(ref).name.lower())
            if by_name:
                return [self._as_ref_candidate(by_name)]
        stem = Path(ref).stem if Path(ref).suffix else ref
        stem_norm = self._norm_reference_stem(stem)
        matches = [p for p in image_paths
                   if self._norm_reference_stem(p.stem) == stem_norm
                   and not self._is_excluded_reference_path(p)]
        nums = re.findall(r"\d+", stem_norm)
        # A numeric-only Excel value is a code, not an exact filename. Always
        # retain every capture ending in that number (for example both 2405 and
        # IMG_2405). Explicit filenames and paths keep their exact behavior.
        if re.fullmatch(r"\d+", stem_norm) and nums:
            matches = list(ref_index.get(nums[-1], []))
        if not matches:
            nums = re.findall(r"\d+", stem_norm)
            if nums:
                matches = list(ref_index.get(nums[-1], []))   # el índice ya excluye salida
        return self._group_ref_candidates(matches)

    def _face_context_for_ambiguous(self, people, person_cands, image_paths):
        """Para las referencias AMBIGUAS (varios candidatos = posibles personas
        DISTINTAS con el mismo número), calcula con OpenCV (NO el motor): la
        fracción de RETRATO por carpeta candidata (sesión de retratos vs familiar)
        y el nº de caras por candidato (setea cand.faces). Devuelve
        (folder_portrait_score, report)."""
        from core.smart_reference_resolver import _norm_folder, SMART_REFERENCE_FACE_CHECK_ENABLED
        if not SMART_REFERENCE_FACE_CHECK_ENABLED or self._haar_cascade() is None:
            return {}, []
        amb_folders: set = set()
        amb_cands = []
        for person in people:
            cands = person_cands[id(person)]
            if len(cands) >= 2:
                for c in cands:
                    amb_folders.add(_norm_folder(c.folder))
                    amb_cands.append(c)
        if not amb_folders:
            return {}, []
        # Fracción de retrato por carpeta candidata (muestra de las fotos del lote).
        by_folder: Dict[str, list] = {}
        for p in image_paths:
            f = _norm_folder(self._ref_folder(p))
            if f in amb_folders and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                by_folder.setdefault(f, []).append(p)
        folder_portrait = {f: round(self._portrait_fraction(ps), 3) for f, ps in by_folder.items()}
        # Nº de caras por candidato ambiguo (para preferir retrato y rechazar familiar).
        for c in amb_cands:
            try:
                c.faces = self._count_faces_opencv(Path(c.path))
            except Exception:
                c.faces = -1
        rep = [{"carpeta": f, "fraccion_retrato": s,
                "tipo": ("retratos" if s >= 0.5 else "familiar/mixta")}
               for f, s in sorted(folder_portrait.items(), key=lambda kv: -kv[1])]
        return folder_portrait, rep

    def _resolve_references_smart(self, people, secure_sources, image_paths,
                                  image_by_name, report) -> int:
        """Resuelve TODAS las referencias en 2 pasos (aditivo, multi-carpeta).
        Única=como antes; varias=scoring por CONTEXTO (densidad/secuencia/origen);
        ambigua/empate=se omite y se reporta. Devuelve nº de hits. El motor solo
        recibe rutas exactas y confiables (o None -> se omite)."""
        from core.smart_reference_resolver import (
            SmartReferenceResolver, RefContext, extract_reference_number, _norm_folder)

        secure_source = secure_sources[0]
        selected_sources = [self._relative_to_workspace(s) for s in secure_sources]
        multi_source = len(secure_sources) >= 2
        ref_index = self._build_reference_index(image_paths)

        # PASO A: candidatos por persona; carpeta dominante (solo BONUS) por
        #         referencias únicas; números del lote por carpeta (densidad).
        person_cands: Dict[int, list] = {}
        folder_unique_count: Dict[str, int] = {}
        batch_numbers: set = set()
        for person in people:
            cands = self._reference_candidates(
                person["reference_value"], secure_source, image_paths, image_by_name, ref_index)
            person_cands[id(person)] = cands
            num = extract_reference_number(person["reference_value"])
            if num:
                batch_numbers.add(num)
            if len(cands) == 1:
                f = cands[0].folder  # casing original (el resolver normaliza al comparar)
                folder_unique_count[f] = folder_unique_count.get(f, 0) + 1
        dominant_folder = (max(folder_unique_count, key=folder_unique_count.get)
                           if folder_unique_count else "")

        # A camera counter may repeat in different folders.  When the same
        # number also appears for several Excel rows, use nearby *unique*
        # references in Excel order as person-specific folder context.  This
        # is only a hint; the resolver still applies all of its conservative
        # score and ambiguity rules.
        number_counts: Dict[str, int] = {}
        person_numbers: Dict[int, str] = {}
        for person in people:
            number = extract_reference_number(person["reference_value"])
            person_numbers[id(person)] = number
            if number:
                number_counts[number] = number_counts.get(number, 0) + 1

        person_neighbor_folder: Dict[int, str] = {}
        for index, person in enumerate(people):
            number = person_numbers.get(id(person), "")
            if not number or number_counts.get(number, 0) <= 1:
                continue
            votes: Dict[str, int] = {}
            for distance in range(1, 7):
                weight = 7 - distance
                for neighbor_index in (index - distance, index + distance):
                    if neighbor_index < 0 or neighbor_index >= len(people):
                        continue
                    neighbor = people[neighbor_index]
                    neighbor_candidates = person_cands.get(id(neighbor), [])
                    if len(neighbor_candidates) != 1:
                        continue
                    folder = neighbor_candidates[0].folder
                    votes[folder] = votes.get(folder, 0) + weight
            if votes:
                ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
                second_score = ranked[1][1] if len(ranked) > 1 else -1
                if ranked[0][1] > second_score:
                    person_neighbor_folder[id(person)] = ranked[0][0]

        # Carpeta(norm) -> números del lote (Excel) presentes en ella. Es la señal
        # clave para multi-fotógrafo: qué carpeta tiene el clúster del salón.
        folder_numbers: Dict[str, set] = {}
        for num in batch_numbers:
            for p in ref_index.get(num, []):
                folder_numbers.setdefault(_norm_folder(self._ref_folder(p)), set()).add(num)

        # RETRATO (OpenCV, no el motor): para las referencias ambiguas (mismo número
        # = posibles personas distintas), detecta la "sesión de retratos" por carpeta
        # y el nº de caras por candidato (setea cand.faces en los ambiguos).
        folder_portrait, portrait_report = self._face_context_for_ambiguous(
            people, person_cands, image_paths)

        # PASO B: decidir
        resolver = SmartReferenceResolver()
        report.setdefault("referencias_resueltas_automaticamente", [])
        report.setdefault("referencias_ambiguas", [])
        report.setdefault("referencias_no_encontradas", [])
        report.setdefault("alumnos_omitidos_por_referencia_dudosa", [])

        resueltas_unicas = 0
        resueltas_smart = 0
        reference_hits = 0
        used_paths_by_number: Dict[str, set] = {}
        for person in people:
            original_cands = person_cands[id(person)]
            # Preserve every distinct capture for the visual pre-audit.  The
            # metadata resolver may still choose a provisional path, but it no
            # longer prevents the face-based layer from seeing alternatives.
            person["reference_candidate_paths"] = [
                Path(candidate.path) for candidate in original_cands
            ]
            num = extract_reference_number(person["reference_value"])
            duplicated_in_excel = bool(num and number_counts.get(num, 0) > 1)
            reserved = used_paths_by_number.setdefault(num, set()) if duplicated_in_excel else set()
            cands = [candidate for candidate in original_cands if candidate.path not in reserved]
            row_folder = person_neighbor_folder.get(id(person), "")
            if duplicated_in_excel and row_folder:
                contextual_candidates = [
                    candidate for candidate in cands
                    if _norm_folder(candidate.folder) == _norm_folder(row_folder)
                ]
                if contextual_candidates:
                    cands = contextual_candidates
            ctx = RefContext(number=num, dominant_folder=(row_folder or dominant_folder),
                             selected_sources=selected_sources,
                             folder_numbers=folder_numbers, multi_source=multi_source,
                             folder_portrait_score=folder_portrait)
            res = resolver.resolve(cands, ctx)
            detail = {
                "persona": person["display_name"],
                "referencia": person["reference_value"],
                "estado": res.status,
                "archivo_elegido": (self._relative_to_workspace(Path(res.chosen))
                                    if res.chosen else "NINGUNO"),
                "score": res.score,
                "motivo": res.reasons,
                "candidatos_encontrados": len(res.candidates),
                "rutas_candidatos": [self._relative_to_workspace(Path(c)) for c in res.candidates],
                "score_por_candidato": [
                    {"archivo": self._relative_to_workspace(Path(cs["path"])),
                     "carpeta": cs["folder"], "score": cs["score"],
                     "dentro_de_origen": cs["in_source"], "motivo": cs["reasons"]}
                    for cs in res.candidate_scores
                ],
                "carpeta_dominante": res.dominant_folder,
                "vecinos_usados": res.neighbors_used,
                "codigo_repetido_en_excel": duplicated_in_excel,
                "carpeta_sugerida_por_vecinos_excel": row_folder,
            }
            if res.chosen:
                if duplicated_in_excel:
                    reserved.add(res.chosen)
                person["reference_path"] = Path(res.chosen)
                reference_hits += 1
                if res.status == "resuelta_automaticamente":
                    resueltas_smart += 1
                    detail["accion"] = "elegida automáticamente entre varios candidatos"
                    report["referencias_resueltas_automaticamente"].append(detail)
                else:
                    resueltas_unicas += 1
            else:
                person["reference_path"] = None
                if res.status == "referencia_no_encontrada":
                    report["referencias_no_encontradas"].append({
                        "persona": person["display_name"],
                        "referencia": person["reference_value"]})
                    report["referencias_faltantes"].append({
                        "persona": person["display_name"],
                        "referencia": person["reference_value"]})
                else:
                    detail["accion"] = "alumno omitido para evitar falso positivo"
                    report["referencias_ambiguas"].append(detail)
                    report["alumnos_omitidos_por_referencia_dudosa"].append({
                        "persona": person["display_name"],
                        "referencia": person["reference_value"],
                        "score_maximo": res.score})

        report["sesiones_retrato_detectadas"] = portrait_report
        repeated_excel_codes = sorted(
            number for number, count in number_counts.items() if count > 1
        )
        report["smart_reference"] = {
            "enabled": True, "dominant_folder": dominant_folder,
            "min_score": resolver.min_score, "min_margin": resolver.min_margin,
            "modo_multi_source": multi_source,
            "codigos_repetidos_excel": repeated_excel_codes,
            "asignacion_uno_a_uno": True,
        }
        report["smart_reference_summary"] = {
            "total_referencias": len(people),
            "resueltas_unicas": resueltas_unicas,
            "resueltas_por_smart": resueltas_smart,
            "ambiguas": len(report["referencias_ambiguas"]),
            "no_encontradas": len(report["referencias_no_encontradas"]),
            "carpeta_dominante": dominant_folder,
            "carpetas_origen_detectadas": selected_sources,
            "sesiones_retrato_detectadas": portrait_report,
            "modo_multi_source": multi_source,
            "min_score": resolver.min_score,
            "min_margin": resolver.min_margin,
            "codigos_repetidos_excel": repeated_excel_codes,
            "asignacion_uno_a_uno": True,
        }
        return reference_hits

    def _collect_mock_matches(
        self,
        people: List[Dict[str, Any]],
        image_paths: List[Path],
        image_by_name: Dict[str, Path],
        mock_face_matches: Optional[Dict[str, List[str]]],
    ) -> Dict[Path, List[Dict[str, Any]]]:
        if mock_face_matches is None:
            return {}
        match_map: Dict[Path, List[Dict[str, Any]]] = {}
        images_by_relative = {self._relative_to_workspace(path).lower().replace("\\", "/"): path for path in image_paths}
        for person in people:
            names = mock_face_matches.get(person["display_name"]) or mock_face_matches.get(person["folder_name"]) or []
            if person.get("reference_path"):
                names = list(dict.fromkeys([person["reference_path"].name, *names]))
            for face_idx, name in enumerate(names):
                image_path = (
                    image_by_name.get(str(name).lower())
                    or images_by_relative.get(str(name).lower().replace("\\", "/"))
                )
                if image_path:
                    match_map.setdefault(image_path, []).append({
                        "person": person, 
                        "distance": 0.0, 
                        "verified": True,
                        "face_index": face_idx,
                        "match_type": "secure"
                    })
        return match_map

    def _select_index_candidates(
        self,
        refs_with_embeddings: List[Dict[str, Any]],
        image_paths: List[Path],
        *,
        model_name: str,
        detector_backend: str,
        DeepFace: Any,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[List[Path], Dict[str, Any]]:
        """Broad preview index for large CR2 batches.

        Every RAW is visited once through its embedded JPEG. Photos selected by
        distance, per-identity top-K, missing preview faces, references and
        sequence neighbors are sent to the unchanged full-quality motor.
        """
        mode = os.environ.get("FACESYNC_FAST_INDEX", "auto").strip().lower()
        raw_count = sum(path.suffix.lower() in self.RAW_EXTENSIONS for path in image_paths)
        cr2_count = sum(path.suffix.lower() == ".cr2" for path in image_paths)
        cr3_count = sum(path.suffix.lower() == ".cr3" for path in image_paths)
        raw_ratio = raw_count / max(1, len(image_paths))
        enabled = mode in {"on", "1", "true", "force"} or (
            mode == "auto"
            and len(image_paths) >= self.FAST_INDEX_MIN_IMAGES
            and raw_ratio >= self.FAST_INDEX_MIN_CR2_RATIO
        )
        stats: Dict[str, Any] = {
            "enabled": enabled,
            "mode": mode,
            "total_photos": len(image_paths),
            "raw_photos": raw_count,
            "cr2_photos": cr2_count,
            "cr3_photos": cr3_count,
        }
        if not enabled:
            stats["selected_photos"] = len(image_paths)
            return list(image_paths), stats

        reference_paths = {
            entry["path"].resolve(strict=False) for entry in refs_with_embeddings
        }
        identity_vectors: Dict[str, List[list]] = {}
        for entry in refs_with_embeddings:
            folder = entry["person"]["folder_name"]
            identity_vectors.setdefault(folder, []).extend(
                face["embedding"] for face in entry.get("candidate_faces", [])
                if face.get("embedding")
            )
        if not identity_vectors:
            stats.update({"enabled": False, "reason": "no_reference_embeddings",
                          "selected_photos": len(image_paths)})
            return list(image_paths), stats

        threshold = float(os.environ.get(
            "FACESYNC_FAST_INDEX_DISTANCE", self.FAST_INDEX_CANDIDATE_DISTANCE
        ))
        selected = set(reference_paths)
        top_by_identity: Dict[str, List[Tuple[float, Path]]] = {
            identity: [] for identity in identity_vectors
        }
        preview_faces = 0
        preview_no_faces = 0
        preview_fallbacks = 0
        preview_errors = 0
        started = time.perf_counter()

        try:
            import numpy as np
        except ImportError:
            np = None

        identity_matrices: Dict[str, Any] = {}
        if np is not None:
            for identity, vectors in identity_vectors.items():
                matrix = np.asarray(vectors, dtype=np.float64)
                matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
                identity_matrices[identity] = matrix

        try:
            preview_workers = int(os.environ.get("FACESYNC_PREVIEW_WORKERS", "2"))
        except ValueError:
            preview_workers = 2
        try:
            preview_batch_size = int(os.environ.get("FACESYNC_PREVIEW_BATCH_SIZE", "16"))
        except ValueError:
            preview_batch_size = 16
        preview_workers = max(1, min(4, preview_workers))
        preview_batch_size = max(1, min(64, preview_batch_size))
        stats["preview_workers"] = preview_workers
        stats["preview_batch_size"] = preview_batch_size

        # JPG/PNG stay in the full motor for safety. CR2 previews are decoded
        # ahead on CPU while the single DirectML consumer handles the previous
        # batch, preserving deterministic image order.
        cr2_work: List[Tuple[int, Path]] = []
        for index, image_path in enumerate(image_paths, 1):
            resolved = image_path.resolve(strict=False)
            if resolved in reference_paths:
                continue
            if image_path.suffix.lower() not in self.RAW_EXTENSIONS:
                selected.add(resolved)
            else:
                cr2_work.append((index, image_path))

        decode_wait_seconds = 0.0
        decode_worker_seconds = 0.0
        preview_inference_seconds = 0.0
        preview_query_seconds = 0.0

        def extract_preview(image_path: Path):
            task_started = time.perf_counter()
            preview_path, status = self._cr2_preview_to_jpeg(image_path)
            return preview_path, status, time.perf_counter() - task_started

        def process_preview_faces(image_path: Path, faces: Any) -> None:
            nonlocal preview_faces, preview_no_faces, preview_errors, preview_query_seconds
            resolved = image_path.resolve(strict=False)
            if faces is None:
                selected.add(resolved)
                preview_errors += 1
                return
            if not faces:
                selected.add(resolved)
                preview_no_faces += 1
                return
            detected_faces = [
                face for face in faces
                if float(face.get("face_confidence") or 0.0) > 0.0
            ]
            if not detected_faces:
                selected.add(resolved)
                preview_no_faces += 1
                return
            embeddings = [
                face["embedding"] for face in detected_faces if face.get("embedding")
            ]
            preview_faces += len(embeddings)
            if not embeddings:
                selected.add(resolved)
                return

            query_started = time.perf_counter()
            if np is not None:
                left = np.asarray(embeddings, dtype=np.float64)
                left /= np.maximum(np.linalg.norm(left, axis=1, keepdims=True), 1e-12)
            else:
                left = None
            for identity, vectors in identity_vectors.items():
                if np is not None:
                    distance = float(np.min(1.0 - left @ identity_matrices[identity].T))
                else:
                    distance = min(
                        self._cosine_distance(face, reference)
                        for face in embeddings for reference in vectors
                    )
                top_by_identity[identity].append((distance, image_path))
                if distance <= threshold:
                    selected.add(resolved)
            preview_query_seconds += time.perf_counter() - query_started

        from collections import deque
        from concurrent.futures import ThreadPoolExecutor
        work_iter = iter(cr2_work)
        pending = deque()
        window = max(preview_batch_size * 2, preview_workers * 2)

        def submit_next(executor) -> bool:
            try:
                index, image_path = next(work_iter)
            except StopIteration:
                return False
            pending.append((index, image_path, executor.submit(extract_preview, image_path)))
            return True

        with ThreadPoolExecutor(
            max_workers=preview_workers, thread_name_prefix="facesync-preview"
        ) as executor:
            for _ in range(min(window, len(cr2_work))):
                submit_next(executor)
            while pending:
                if cancel_event is not None and cancel_event.is_set():
                    raise _FaceSyncCancelled()
                prepared: List[Tuple[int, Path, Optional[Path]]] = []
                while pending and len(prepared) < preview_batch_size:
                    index, image_path, future = pending.popleft()
                    wait_started = time.perf_counter()
                    try:
                        preview_path, status, worker_seconds = future.result()
                        decode_worker_seconds += worker_seconds
                    except Exception:
                        preview_path, status = None, "error"
                    decode_wait_seconds += time.perf_counter() - wait_started
                    submit_next(executor)
                    if status == "full_fallback":
                        preview_fallbacks += 1
                    if preview_path is None:
                        selected.add(image_path.resolve(strict=False))
                        preview_errors += 1
                    prepared.append((index, image_path, preview_path))

                valid_items = [
                    (image_path, preview_path)
                    for _index, image_path, preview_path in prepared
                    if preview_path is not None
                ]
                if valid_items:
                    inference_started = time.perf_counter()
                    batch_faces = self._get_preview_embeddings_batch(
                        valid_items,
                        model_name=model_name,
                        detector_backend=detector_backend,
                        DeepFace=DeepFace,
                        metrics=stats,
                    )
                    preview_inference_seconds += time.perf_counter() - inference_started
                    for image_path, _preview_path in valid_items:
                        process_preview_faces(image_path, batch_faces.get(image_path))

                if progress_callback and prepared:
                    current = prepared[-1][0]
                    progress_callback({
                        "event": "progress", "stage": "indexing_faces",
                        "current": current, "total": len(image_paths),
                        "percent": int(current / max(1, len(image_paths)) * 100),
                        "message": f"Indexando vistas previas RAW {current}/{len(image_paths)}...",
                    })

        for candidates in top_by_identity.values():
            candidates.sort(key=lambda item: item[0])
            for _distance, path in candidates[:self.FAST_INDEX_TOP_PER_IDENTITY]:
                selected.add(path.resolve(strict=False))

        # Sequence safety: packages are normally photographic bursts. Neighbors
        # cover preview-distance drift and family/group transitions.
        by_folder: Dict[Path, List[Path]] = {}
        for path in image_paths:
            by_folder.setdefault(path.parent.resolve(strict=False), []).append(path)
        expanded = set(selected)
        radius = self.FAST_INDEX_NEIGHBOR_RADIUS
        for folder_paths in by_folder.values():
            for position, path in enumerate(folder_paths):
                if path.resolve(strict=False) not in selected:
                    continue
                start = max(0, position - radius)
                end = min(len(folder_paths), position + radius + 1)
                expanded.update(
                    neighbor.resolve(strict=False) for neighbor in folder_paths[start:end]
                )

        result = [
            path for path in image_paths if path.resolve(strict=False) in expanded
        ]
        stats.update({
            "distance_threshold": threshold,
            "top_per_identity": self.FAST_INDEX_TOP_PER_IDENTITY,
            "neighbor_radius": radius,
            "preview_faces": preview_faces,
            "preview_no_faces_promoted": preview_no_faces,
            "preview_full_fallbacks": preview_fallbacks,
            "preview_errors_promoted": preview_errors,
            "preview_decode_wait_seconds": round(decode_wait_seconds, 3),
            "preview_decode_worker_seconds_sum": round(decode_worker_seconds, 3),
            "preview_inference_seconds": round(preview_inference_seconds, 3),
            "preview_query_seconds": round(preview_query_seconds, 3),
            "selected_photos": len(result),
            "reduction_percent": round(
                (1.0 - len(result) / max(1, len(image_paths))) * 100, 1
            ),
            "index_seconds": round(time.perf_counter() - started, 3),
        })
        return result, stats

    def _collect_deepface_matches(
        self,
        people: List[Dict[str, Any]],
        image_paths: List[Path],
        *,
        threshold: float,
        model_name: str,
        detector_backend: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        batch_size: int = 25,
    ) -> Tuple[Dict[Path, List[Dict[str, Any]]], Dict[str, Any]]:
        """
        Premium multi-face embedding-based face matching.

        For each candidate photo, detects ALL faces and compares each
        face independently against all reference embeddings.

        Returns:
            match_map: {image_path -> [{person, distance, verified, face_index, match_type}]}
            errors: {"deepface": [...], "imagen": [...], "referencias_invalidas": [...]}
        """
        try:
            from deepface import DeepFace
        except Exception as exc:
            # Exponer la causa REAL (DLL/módulo/CPU) en vez de un mensaje genérico:
            # así un fallo de empaque/entorno es diagnosticable desde la UI.
            raise RuntimeError(
                f"No se pudo cargar deepface: {type(exc).__name__}: {exc}"
            ) from exc

        collect_started = time.perf_counter()
        backend_started = time.perf_counter()
        self._enable_gpu_backend(model_name, detector_backend)
        self._performance_stats["backend_init_seconds"] = round(
            time.perf_counter() - backend_started, 3
        )

        match_map: Dict[Path, List[Dict[str, Any]]] = {}
        errors: Dict[str, Any] = {
            "deepface": [],
            "imagen": [],
            "referencias_invalidas": [],
            "seleccion_rostros_referencia": [],
            "seleccion_referencia_cr3": [],
            "referencias_ambiguas_por_rostro": [],
            "preauditoria_referencias": [],
            "auditoria_referencias_historicas": [],
        }
        photo_face_embeddings: Dict[Path, List[list]] = {}
        # Cache performance metrics
        cache_hits = 0
        cache_misses = 0
        # Metricas RAW totales y separadas por formato. Los campos CR2 se
        # conservan para compatibilidad con reportes anteriores.
        cr2_metrics = {
            "raw_detectadas": sum(
                1 for p in image_paths if p.suffix.lower() in self.RAW_EXTENSIONS
            ),
            "cr2_detectadas": sum(1 for p in image_paths if p.suffix.lower() == ".cr2"),
            "cr3_detectadas": sum(1 for p in image_paths if p.suffix.lower() == ".cr3"),
            "raw_convertidas": 0,
            "raw_cache_hits": 0,
            "raw_prefetch_convertidas": 0,
            "raw_prefetch_cache_hits": 0,
            "raw_errores": 0,
            "raw_ignoradas_por_dependencia": 0,
            "cr2_convertidas": 0,
            "cr2_cache_hits": 0,
            "cr2_prefetch_convertidas": 0,
            "cr2_prefetch_cache_hits": 0,
            "cr2_errores": 0,
            "cr2_ignoradas_por_dependencia": 0,
            "cr3_convertidas": 0,
            "cr3_cache_hits": 0,
            "cr3_prefetch_convertidas": 0,
            "cr3_prefetch_cache_hits": 0,
            "cr3_errores": 0,
            "cr3_ignoradas_por_dependencia": 0,
        }

        # --- Phase 1: Extract every face from each reference ---
        references_started = time.perf_counter()
        refs_with_embeddings: List[Dict[str, Any]] = []
        reference_plan: List[Tuple[Dict[str, Any], Path, int]] = []
        for person in people:
            candidate_paths = list(person.get("reference_candidate_paths") or [])
            if not candidate_paths and person.get("reference_path"):
                candidate_paths = [person["reference_path"]]
            unique_paths: List[Path] = []
            seen_paths: set = set()
            for candidate_path in candidate_paths:
                path = Path(candidate_path)
                resolved = path.resolve(strict=False)
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                unique_paths.append(path)
            for path in unique_paths:
                reference_plan.append((person, path, len(unique_paths)))

        refs_total = len(reference_plan)
        refs_current = 0
        extracted_reference_faces: Dict[Path, Any] = {}
        for person, reference_path, candidate_count in reference_plan:
            refs_current += 1
            if cancel_event is not None and cancel_event.is_set():
                raise _FaceSyncCancelled()
            if progress_callback and (refs_current == 1 or refs_current % max(1, batch_size) == 0 or refs_current == refs_total):
                progress_callback({
                    "event": "progress",
                    "stage": "extracting_references",
                    "current": refs_current,
                    "total": refs_total,
                    "percent": int((refs_current / max(1, refs_total)) * 100),
                    "message": f"Extrayendo referencias {refs_current}/{refs_total}...",
                    "person": person.get("display_name", ""),
                })
            # Extract ALL faces from reference to validate
            resolved_reference = reference_path.resolve(strict=False)
            if resolved_reference in extracted_reference_faces:
                ref_faces = extracted_reference_faces[resolved_reference]
            else:
                reference_cache_model = (
                    f"{model_name}:{self.CR3_PREVIEW_CACHE_VARIANT}"
                    if reference_path.suffix.lower() == ".cr3"
                    else model_name
                )
                was_cached = self._is_cached(reference_path, reference_cache_model)
                ref_faces = self._get_all_face_embeddings(
                    reference_path, model_name=model_name,
                    detector_backend=detector_backend, DeepFace=DeepFace,
                    cr2_metrics=cr2_metrics,
                )
                extracted_reference_faces[resolved_reference] = ref_faces
                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1
            if ref_faces is None:
                # Image error
                errors["referencias_invalidas"].append({
                    "persona": person["display_name"],
                    "foto": self._relative_to_workspace(reference_path),
                    "error": "Error al procesar la foto de referencia.",
                    "rostros_detectados": 0,
                })
                continue
            if len(ref_faces) == 0:
                errors["referencias_invalidas"].append({
                    "persona": person["display_name"],
                    "foto": self._relative_to_workspace(reference_path),
                    "error": "No se detecto ningun rostro en la referencia.",
                    "rostros_detectados": 0,
                })
                continue
            refs_with_embeddings.append({
                "person": person,
                "candidate_faces": ref_faces,
                "path": reference_path,
                "ref_faces_count": len(ref_faces),
                "reference_candidate_count": candidate_count,
                "reference_preselected": bool(
                    person.get("reference_path")
                    and Path(person["reference_path"]).resolve(strict=False)
                    == resolved_reference
                ),
            })

        if not refs_with_embeddings:
            errors["cache_metrics"] = {"hits": cache_hits, "misses": cache_misses}
            errors["cr2_metrics"] = cr2_metrics
            errors["photo_face_embeddings"] = {}
            errors["photo_face_details"] = {}
            errors["refs_with_embeddings"] = []
            errors["facial_index_stats"] = {
                "enabled": False,
                "reason": "no_valid_references",
                "total_photos": len(image_paths),
                "selected_photos": len(image_paths),
            }
            errors["performance_stats"] = dict(self._performance_stats)
            self._disable_gpu_backend()
            return match_map, errors

        self._performance_stats["reference_seconds"] = round(
            time.perf_counter() - references_started, 3
        )

        # A large CR2 set is indexed once from its embedded JPEG previews. The
        # result is only a broad candidate union; all final decisions remain in
        # the patched full-quality motor below.
        full_image_paths, facial_index_stats = self._select_index_candidates(
            refs_with_embeddings,
            image_paths,
            model_name=model_name,
            detector_backend=detector_backend,
            DeepFace=DeepFace,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        errors["facial_index_stats"] = facial_index_stats
        self._performance_stats["facial_index"] = facial_index_stats

        # --- Phase 2: Extract candidate faces once, before choosing the
        # reference identity. Recurrence cannot be measured without seeing the
        # batch. Reference photos reuse the faces already extracted above.
        ref_by_resolved = {
            ref["path"].resolve(strict=False): ref for ref in refs_with_embeddings
        }
        photo_faces_by_path: Dict[Path, List[Dict[str, Any]]] = {}
        photos_total = len(full_image_paths)
        last_progress_time = time.monotonic()
        extraction_started = time.perf_counter()
        self._start_cr2_prefetch(full_image_paths)
        for photo_idx, image_path in enumerate(full_image_paths, 1):
            if cancel_event is not None and cancel_event.is_set():
                raise _FaceSyncCancelled()
            now = time.monotonic()
            if progress_callback and (
                photo_idx == 1
                or photo_idx == photos_total
                or now - last_progress_time >= 0.5
            ):
                last_progress_time = now
                progress_callback({
                    "event": "progress",
                    "stage": "extracting_faces",
                    "current": photo_idx,
                    "total": photos_total,
                    "percent": int((photo_idx / max(1, photos_total)) * 100),
                    "message": f"Analizando rostros {photo_idx}/{photos_total}...",
                    "photo": self._relative_to_workspace(image_path),
                })

            resolved_photo = image_path.resolve(strict=False)
            ref_entry = ref_by_resolved.get(resolved_photo)
            if ref_entry is not None:
                photo_faces = ref_entry["candidate_faces"]
            else:
                if image_path.suffix.lower() in self.RAW_EXTENSIONS:
                    self._await_cr2_prefetch(image_path, cr2_metrics)
                image_cache_model = (
                    f"{model_name}:{self.CR3_PREVIEW_CACHE_VARIANT}"
                    if image_path.suffix.lower() == ".cr3"
                    else model_name
                )
                was_cached = self._is_cached(image_path, image_cache_model)
                try:
                    photo_faces = self._get_all_face_embeddings(
                        image_path,
                        model_name=model_name,
                        detector_backend=detector_backend,
                        DeepFace=DeepFace,
                        cr2_metrics=cr2_metrics,
                    )
                except Exception as exc:
                    errors["imagen"].append({
                        "foto": self._relative_to_workspace(image_path),
                        "error": str(exc),
                    })
                    cache_misses += 1
                    continue
                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1

            if not photo_faces:
                continue
            photo_faces_by_path[image_path] = photo_faces
            photo_face_embeddings[image_path] = [
                face["embedding"] for face in photo_faces
            ]

        self._stop_cr2_prefetch(wait=True)
        extraction_seconds = time.perf_counter() - extraction_started
        self._performance_stats["candidate_extraction_seconds"] = round(extraction_seconds, 3)
        self._performance_stats["candidate_images_per_second"] = round(
            photos_total / max(0.001, extraction_seconds), 3
        )

        # Capa exclusiva CR3: fortalece una referencia natural con una sola
        # ancla operativa respaldada, manteniendo embeddings preview/Full RAW
        # separados. Si no hay evidencia suficiente, deja intacta la referencia.
        cr3_reference_details, cr3_reference_stats = self._strengthen_cr3_references(
            refs_with_embeddings=refs_with_embeddings,
            photo_faces_by_path=photo_faces_by_path,
            image_paths=full_image_paths,
            model_name=model_name,
            detector_backend=detector_backend,
            DeepFace=DeepFace,
            cancel_event=cancel_event,
        )
        errors["seleccion_referencia_cr3"] = cr3_reference_details
        errors["cr3_reference_selector"] = cr3_reference_stats
        self._performance_stats["cr3_reference_selector"] = cr3_reference_stats

        candidate_refs, all_selection_details, candidate_ambiguous_refs = (
            self._select_reference_faces_by_recurrence(
                refs_with_embeddings,
                photo_faces_by_path,
            )
        )
        refs_with_embeddings, preaudit_details = self._select_reference_candidates_global(
            candidate_refs,
            people,
        )
        historical_audits = [
            detail for detail in preaudit_details
            if detail.get("codigo_repetido_historico")
        ]
        errors["auditoria_referencias_historicas"] = historical_audits
        for detail in historical_audits:
            if detail.get("resuelta", True):
                continue
            candidate_ambiguous_refs.append({
                "persona": detail.get("persona", ""),
                "foto": detail.get("archivo_elegido", "NINGUNO"),
                "referencia": detail.get("referencia_excel", ""),
                "motivo": detail.get(
                    "motivo",
                    "Todos los candidatos pertenecen a identidades historicas.",
                ),
                "tipo": "codigo_repetido_historico_sin_candidato_nuevo",
            })
        quarantine_revalidations = self._revalidate_reference_trust_after_preaudit(
            refs_with_embeddings,
            preaudit_details,
            photo_faces_by_path,
        )
        selected_pairs = {
            (
                str(ref["person"].get("display_name", "")),
                self._relative_to_workspace(Path(ref["path"])),
            )
            for ref in refs_with_embeddings
        }
        selected_people = {pair[0] for pair in selected_pairs}
        selection_details = [
            detail for detail in all_selection_details
            if (str(detail.get("persona", "")), str(detail.get("foto", "")))
            in selected_pairs
        ]
        revalidation_by_pair = {
            (item["persona"], item["foto"]): item
            for item in quarantine_revalidations
        }
        for detail in selection_details:
            key = (str(detail.get("persona", "")), str(detail.get("foto", "")))
            revalidation = revalidation_by_pair.get(key)
            if not revalidation:
                continue
            detail["referencia_confiable"] = True
            detail["motivos_cuarentena"] = []
            detail["soportes_reclamados_por_otras_identidades_post_preauditoria"] = (
                revalidation["soportes_reclamados"]
            )
            detail["cuarentena_revalidada_post_preauditoria"] = True
        revalidation_by_person = {
            item["persona"]: item for item in quarantine_revalidations
        }
        for detail in preaudit_details:
            revalidation = revalidation_by_person.get(str(detail.get("persona", "")))
            if revalidation:
                detail["cuarentena_revalidada_post_preauditoria"] = True
        ambiguous_refs = [
            detail for detail in candidate_ambiguous_refs
            if str(detail.get("persona", "")) not in selected_people
        ]
        errors["seleccion_rostros_referencia"] = selection_details
        errors["referencias_ambiguas_por_rostro"] = ambiguous_refs
        errors["preauditoria_referencias"] = preaudit_details

        if not refs_with_embeddings:
            errors["cache_metrics"] = {"hits": cache_hits, "misses": cache_misses}
            errors["cr2_metrics"] = cr2_metrics
            errors["photo_face_embeddings"] = photo_face_embeddings
            errors["photo_face_details"] = photo_faces_by_path
            errors["refs_with_embeddings"] = []
            return match_map, errors

        # --- Phase 3: Build one identity embedding per person ---
        try:
            import numpy as np
            _use_numpy = True
        except ImportError:
            _use_numpy = False

        flat_reference_faces = [
            {"person": ref["person"], "embedding": ref["embedding"]}
            for ref in refs_with_embeddings
        ]

        if _use_numpy:
            ref_matrix = np.array([r["embedding"] for r in flat_reference_faces], dtype=np.float64)
            # L2-normalize rows for fast cosine via dot product: dist = 1 - dot(a, b)
            ref_norms = np.linalg.norm(ref_matrix, axis=1, keepdims=True)
            ref_norms = np.where(ref_norms == 0, 1.0, ref_norms)
            ref_matrix_normed = ref_matrix / ref_norms
        else:
            ref_matrix_normed = None

        # --- Phase 4: Compare every candidate face with selected identities ---
        matching_started = time.perf_counter()
        ref_paths_resolved = {r["path"].resolve(strict=False) for r in refs_with_embeddings}
        last_progress_time = time.monotonic()
        last_yield_time = time.monotonic()

        for photo_idx, image_path in enumerate(full_image_paths, 1):
            # Time-based GIL yield: yield every ~50ms instead of every photo
            now = time.monotonic()
            if now - last_yield_time >= 0.05:
                time.sleep(0.001)
                last_yield_time = now
            if cancel_event is not None and cancel_event.is_set():
                raise _FaceSyncCancelled()

            # Throttled progress: emit at most every 0.5s or on first/last photo
            if progress_callback and (photo_idx == 1 or photo_idx == photos_total or now - last_progress_time >= 0.5):
                last_progress_time = now
                progress_callback({
                    "event": "progress",
                    "stage": "comparing",
                    "current": photo_idx,
                    "total": photos_total,
                    "percent": int((photo_idx / max(1, photos_total)) * 100),
                    "message": f"Procesando fotos {photo_idx}/{photos_total}...",
                    "photo": self._relative_to_workspace(image_path),
                })

            resolved_photo = image_path.resolve(strict=False)

            # If the photo IS one of the references, auto-match distance=0
            if resolved_photo in ref_paths_resolved:
                for ref in refs_with_embeddings:
                    if ref["path"].resolve(strict=False) == resolved_photo:
                        match_map.setdefault(image_path, []).append({
                            "person": ref["person"], "distance": 0.0,
                            "verified": True, "face_index": 0,
                            "match_type": "secure",
                        })
                continue

            photo_faces = photo_faces_by_path.get(image_path)
            if not photo_faces:
                continue  # No faces detected, will go to Pendientes

            # --- Vectorized comparison: all faces in photo vs all refs at once ---
            if _use_numpy and ref_matrix_normed is not None:
                import numpy as np
                face_embs = np.array([f["embedding"] for f in photo_faces], dtype=np.float64)
                face_norms = np.linalg.norm(face_embs, axis=1, keepdims=True)
                face_norms = np.where(face_norms == 0, 1.0, face_norms)
                face_embs_normed = face_embs / face_norms
                # dist_matrix shape: (num_faces_in_photo, num_refs)
                dot_matrix = face_embs_normed @ ref_matrix_normed.T
                dist_matrix = 1.0 - dot_matrix

                for face_idx in range(dist_matrix.shape[0]):
                    # One result per person, using the minimum distance across
                    # all faces in that person's reference image. This mirrors
                    # DeepFace.verify instead of guessing one reference face.
                    best_by_person: Dict[str, Dict[str, Any]] = {}
                    for ref_idx in range(dist_matrix.shape[1]):
                        distance = float(dist_matrix[face_idx, ref_idx])
                        ref_person = flat_reference_faces[ref_idx]["person"]
                        person_key = ref_person["folder_name"]
                        previous = best_by_person.get(person_key)
                        if previous is None or distance < previous["distance"]:
                            best_by_person[person_key] = {
                                "person": ref_person,
                                "distance": distance,
                            }
                    for best in best_by_person.values():
                        distance = best["distance"]
                        if distance <= threshold:
                            match_type = "secure" if distance <= self.THRESHOLD_SECURE else "review"
                            match_map.setdefault(image_path, []).append({
                                "person": best["person"],
                                "distance": distance,
                                "verified": match_type == "secure",
                                "face_index": face_idx,
                                "match_type": match_type,
                                "faces_in_photo": len(photo_faces),
                            })
            else:
                # Fallback: per-face Python loop
                for face_idx, face_data in enumerate(photo_faces):
                    face_emb = face_data["embedding"]
                    for ref in refs_with_embeddings:
                        distance = min(
                            self._cosine_distance(ref_embedding, face_emb)
                            for ref_embedding in ref.get("embeddings", [ref["embedding"]])
                        )
                        if distance <= threshold:
                            match_type = "secure" if distance <= self.THRESHOLD_SECURE else "review"
                            match_map.setdefault(image_path, []).append({
                                "person": ref["person"],
                                "distance": distance,
                                "verified": match_type == "secure",
                                "face_index": face_idx,
                                "match_type": match_type,
                                "faces_in_photo": len(photo_faces),
                            })

        # Attach cache metrics and gallery inputs to errors dict for the caller
        errors["cache_metrics"] = {"hits": cache_hits, "misses": cache_misses}
        errors["cr2_metrics"] = cr2_metrics
        errors["photo_face_embeddings"] = photo_face_embeddings
        errors["photo_face_details"] = photo_faces_by_path
        errors["refs_with_embeddings"] = refs_with_embeddings
        self._performance_stats["matching_seconds"] = round(
            time.perf_counter() - matching_started, 3
        )
        self._performance_stats["embedding_pipeline_seconds"] = round(
            time.perf_counter() - collect_started, 3
        )
        errors["performance_stats"] = dict(self._performance_stats)
        self._disable_gpu_backend()
        return match_map, errors

    def _cluster_embedding_items(
        self,
        items: List[Dict[str, Any]],
        *,
        max_distance: float,
    ) -> List[List[Dict[str, Any]]]:
        """Return deterministic visual components without identity assumptions."""
        if not items:
            return []
        parents = list(range(len(items)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if self._cosine_distance(
                    items[left]["embedding"], items[right]["embedding"]
                ) <= max_distance:
                    union(left, right)

        components: Dict[int, List[Dict[str, Any]]] = {}
        for index, item in enumerate(items):
            components.setdefault(find(index), []).append(item)
        return sorted(
            components.values(),
            key=lambda component: (
                -len(component),
                sum(float(item.get("distance", 999)) for item in component)
                / max(1, len(component)),
                str(component[0].get("path", "")),
            ),
        )

    def _select_reference_faces_by_recurrence(
        self,
        refs: List[Dict[str, Any]],
        photo_faces_by_path: Dict[Path, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Choose one identity face from each reference image.

        A multi-face reference is an unlabeled set: confidence alone cannot tell
        which face owns the Excel name.  Each candidate face therefore receives
        one vote per *distinct photo* where it recurs below the original ArcFace
        threshold. Votes are softly weighted by capture-time proximity when
        timestamps are informative. Face prominence is only a tie-breaker.

        If recurrence does not produce a clear winner, the reference is omitted
        instead of contaminating the identity gallery with an accompanying face.
        """
        if not refs:
            return [], [], []

        reference_paths = {
            ref["path"].resolve(strict=False) for ref in refs
        }
        candidate_items = [
            (path, faces)
            for path, faces in photo_faces_by_path.items()
            if path.resolve(strict=False) not in reference_paths and faces
        ]

        timestamps = []
        for path, _faces in candidate_items:
            try:
                timestamps.append(float(path.stat().st_mtime))
            except OSError:
                continue
        timestamps.sort()
        positive_gaps = [
            right - left
            for left, right in zip(timestamps, timestamps[1:])
            if right > left
        ]
        typical_gap = statistics.median(positive_gaps) if positive_gaps else 0.0
        time_scale = max(
            self.REFERENCE_TIME_SCALE_MIN_SECONDS,
            typical_gap * 10.0,
        )

        selected_refs: List[Dict[str, Any]] = []
        details: List[Dict[str, Any]] = []
        ambiguous: List[Dict[str, Any]] = []

        for ref in refs:
            faces = list(ref.get("candidate_faces") or [])
            if not faces:
                continue

            areas = []
            for face in faces:
                region = face.get("facial_area") or {}
                try:
                    areas.append(max(0.0, float(region.get("w", 0))) * max(0.0, float(region.get("h", 0))))
                except (TypeError, ValueError):
                    areas.append(0.0)
            max_area = max(areas, default=0.0)
            confidences = [max(0.0, float(face.get("face_confidence", 0.0))) for face in faces]
            max_confidence = max(confidences, default=0.0)

            try:
                reference_time = float(ref["path"].stat().st_mtime)
            except OSError:
                reference_time = 0.0

            candidates = []
            for face_index, face in enumerate(faces):
                support_count = 0
                weighted_support = 0.0
                support_distances = []
                support_items: List[Dict[str, Any]] = []
                for photo_path, photo_faces in candidate_items:
                    matched_face = min(
                        photo_faces,
                        key=lambda item: self._cosine_distance(
                            face["embedding"], item["embedding"]
                        ),
                    )
                    distance = self._cosine_distance(
                        face["embedding"], matched_face["embedding"]
                    )
                    if distance > self.REFERENCE_RECURRENCE_THRESHOLD:
                        continue
                    support_count += 1
                    support_distances.append(distance)
                    support_items.append({
                        "embedding": matched_face["embedding"],
                        "path": photo_path.resolve(strict=False),
                        "distance": distance,
                    })
                    if reference_time:
                        try:
                            delta = abs(float(photo_path.stat().st_mtime) - reference_time)
                        except OSError:
                            delta = 0.0
                        weighted_support += math.exp(-delta / time_scale)
                    else:
                        weighted_support += 1.0

                if max_area > 0:
                    prominence = areas[face_index] / max_area
                elif max_confidence > 0:
                    prominence = confidences[face_index] / max_confidence
                else:
                    prominence = 0.0
                median_distance = (
                    statistics.median(support_distances)
                    if support_distances else 999.0
                )
                score = weighted_support + (0.15 * support_count) + (0.35 * prominence)
                candidates.append({
                    "face_index": face_index,
                    "embedding": face["embedding"],
                    "support_count": support_count,
                    "weighted_support": weighted_support,
                    "prominence": prominence,
                    "median_distance": median_distance,
                    "score": score,
                    "support_items": support_items,
                })

            ranked = sorted(
                candidates,
                key=lambda item: (
                    item["score"],
                    item["support_count"],
                    item["prominence"],
                    -item["median_distance"],
                ),
                reverse=True,
            )
            winner = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None
            score_margin = winner["score"] - (runner_up["score"] if runner_up else 0.0)
            ratio = (
                winner["score"] / max(1e-9, runner_up["score"])
                if runner_up else float("inf")
            )

            if len(ranked) == 1:
                clear_winner = True
                method = "referencia_con_un_rostro"
            elif winner["support_count"] > 0:
                clear_winner = (
                    score_margin >= self.REFERENCE_RECURRENCE_MIN_SCORE_MARGIN
                    or ratio >= self.REFERENCE_RECURRENCE_MIN_RATIO
                    or winner["support_count"] >= runner_up["support_count"] + 2
                )
                method = "recurrencia_en_fotos_distintas"
            else:
                prominence_margin = winner["prominence"] - runner_up["prominence"]
                clear_winner = winner["prominence"] >= 0.8 and prominence_margin >= 0.25
                method = "prominencia_sin_recurrencia"

            support_items = list(winner.get("support_items") or [])
            support_components = self._cluster_embedding_items(
                support_items,
                max_distance=self.REFERENCE_SUPPORT_PEER_DISTANCE,
            )
            coherent_support = len(support_components[0]) if support_components else 0
            coherence_ratio = coherent_support / max(1, winner["support_count"])
            other_reference_faces = [
                other_face
                for other_ref in refs
                if other_ref is not ref
                for other_face in (other_ref.get("candidate_faces") or [])
                if other_face.get("embedding")
            ]
            cross_claimed = 0
            for support in support_items:
                if not other_reference_faces:
                    break
                other_distance = min(
                    self._cosine_distance(
                        support["embedding"], other_face["embedding"]
                    )
                    for other_face in other_reference_faces
                )
                if (
                    other_distance <= self.REFERENCE_RECURRENCE_THRESHOLD
                    and float(support["distance"]) - other_distance
                    >= self.REFERENCE_CROSS_IDENTITY_MARGIN
                ):
                    cross_claimed += 1

            enough_evidence = (
                winner["support_count"] >= self.REFERENCE_CONTRADICTION_MIN_SUPPORT
            )
            incoherent_support = (
                enough_evidence
                and coherence_ratio < self.REFERENCE_MIN_COHERENCE_RATIO
            )
            cross_identity_support = (
                enough_evidence
                and cross_claimed >= 2
                and cross_claimed / max(1, winner["support_count"]) >= 0.40
            )
            winner_region = faces[winner["face_index"]].get("facial_area") or {}
            try:
                winner_min_side = min(
                    float(winner_region.get("w", 0)),
                    float(winner_region.get("h", 0)),
                )
            except (TypeError, ValueError):
                winner_min_side = 0.0
            low_resolution_reference = (
                winner_min_side > 0
                and winner_min_side < self.REFERENCE_MIN_FACE_SIDE_PIXELS
            )
            # Natural pose variation may fragment a perfectly good reference
            # (e.g. profile vs frontal). Fragmentation is diagnostic; it only
            # quarantines when the anchor itself is also below reliable pixel
            # resolution. Cross-identity ownership remains independently fatal.
            reference_trusted = not (
                low_resolution_reference or cross_identity_support
            )
            quarantine_reasons = []
            if incoherent_support and low_resolution_reference:
                quarantine_reasons.append("soporte_visual_fragmentado")
            if low_resolution_reference:
                quarantine_reasons.append("rostro_referencia_demasiado_pequeno")
            if cross_identity_support:
                quarantine_reasons.append("soporte_reclamado_por_otras_identidades")

            base_detail = {
                "persona": ref["person"]["display_name"],
                "foto": self._relative_to_workspace(ref["path"]),
                "rostros_detectados": len(faces),
                "rostro_seleccionado": winner["face_index"] + 1 if clear_winner else None,
                "soporte_fotos": winner["support_count"],
                "soporte_ponderado": round(winner["weighted_support"], 4),
                "score": round(winner["score"], 4),
                "margen_score": round(score_margin, 4),
                "metodo": method,
                "soporte_coherente": coherent_support,
                "proporcion_coherencia": round(coherence_ratio, 4),
                "soportes_reclamados_por_otras_identidades": cross_claimed,
                "referencia_confiable": reference_trusted,
                "motivos_cuarentena": quarantine_reasons,
                "lado_minimo_rostro_referencia_px": round(winner_min_side, 2),
            }

            if not clear_winner:
                base_detail["motivo"] = (
                    "Varios rostros tienen recurrencia similar; se omite la identidad para evitar contaminación."
                )
                base_detail["candidatos"] = [
                    {
                        "rostro": item["face_index"] + 1,
                        "soporte_fotos": item["support_count"],
                        "score": round(item["score"], 4),
                    }
                    for item in ranked
                ]
                ambiguous.append(base_detail)
                continue

            selected = dict(ref)
            selected["embedding"] = winner["embedding"]
            selected["embeddings"] = [winner["embedding"]]
            selected["selected_face_index"] = winner["face_index"]
            selected["reference_trusted"] = reference_trusted
            selected["reference_quarantine_reasons"] = quarantine_reasons
            selected["reference_support_count"] = winner["support_count"]
            selected["reference_coherent_support"] = coherent_support
            selected["reference_coherence_ratio"] = coherence_ratio
            selected["reference_selection_score"] = winner["score"]
            selected_refs.append(selected)
            details.append(base_detail)

        return selected_refs, details, ambiguous

    def _match_historical_identity(
        self,
        embedding: list,
        records: List[Dict[str, Any]],
        *,
        format_family: str = "",
        representation: str = "",
        processing_version: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Return a strict prior-owner match for one selected reference face."""
        matches: List[Dict[str, Any]] = []
        for record in records or []:
            record_family = str(record.get("format_family", "legacy")).casefold()
            record_representation = str(
                record.get("representation", "legacy")
            ).casefold()
            record_version = str(record.get("processing_version", "legacy"))
            requested_family = str(format_family or "").casefold()
            if requested_family == "cr3":
                if (
                    record_family != "cr3"
                    or record_representation != str(representation).casefold()
                    or record_version != str(processing_version)
                ):
                    continue
            elif requested_family and record_family == "cr3":
                # JPG/CR2 retain their historical behavior, but never compare
                # against a route-specific CR3 embedding.
                continue
            anchors = [
                anchor for anchor in (record.get("embeddings") or [])
                if isinstance(anchor, list) and anchor
            ]
            if not anchors:
                continue
            distances = sorted(
                self._cosine_distance(embedding, anchor) for anchor in anchors
            )
            best_distance = distances[0]
            secure_votes = sum(
                distance <= self.HISTORICAL_IDENTITY_MULTI_ANCHOR_MAX_DISTANCE
                for distance in distances
            )
            if len(anchors) == 1:
                accepted = (
                    best_distance
                    <= self.HISTORICAL_IDENTITY_SINGLE_ANCHOR_MAX_DISTANCE
                )
            else:
                required_votes = min(
                    self.HISTORICAL_IDENTITY_MIN_ANCHOR_VOTES,
                    len(anchors),
                )
                accepted = secure_votes >= required_votes
            if not accepted:
                continue
            matches.append({
                "record": record,
                "best_distance": best_distance,
                "secure_votes": secure_votes,
                "anchor_count": len(anchors),
                "two_best_average": (
                    sum(distances[:2]) / min(2, len(distances))
                ),
            })
        if not matches:
            return None
        winner = min(
            matches,
            key=lambda item: (
                float(item["best_distance"]),
                float(item["two_best_average"]),
                -int(item["secure_votes"]),
                str(item["record"].get("identity_id", "")),
            ),
        )
        record = winner["record"]
        return {
            "identity_id": record.get("identity_id", ""),
            "student": record.get("student", ""),
            "salon": record.get("salon", ""),
            "code": record.get("code", ""),
            "best_distance": round(float(winner["best_distance"]), 6),
            "two_best_average": round(float(winner["two_best_average"]), 6),
            "secure_votes": int(winner["secure_votes"]),
            "anchor_count": int(winner["anchor_count"]),
            "format_family": record.get("format_family", "legacy"),
            "representation": record.get("representation", "legacy"),
            "processing_version": record.get("processing_version", "legacy"),
        }

    def _select_reference_candidates_global(
        self,
        refs: List[Dict[str, Any]],
        people: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Choose one distinct visual reference per Excel identity.

        This is a pre-audit layer, not a recognition change. Every numeric
        filename candidate has already been embedded with the existing motor.
        We cluster only very-close candidate faces, seed identities that have a
        single visual group, then iteratively remove groups already owned by a
        previously secured identity. This repairs chains such as
        Aguirre -> Armenta -> Arrio before the identity gallery is built.
        """
        if not refs:
            return [], []

        def person_key(person: Dict[str, Any]) -> str:
            return str(person.get("folder_name") or person.get("display_name") or id(person))

        valid_refs = [ref for ref in refs if ref.get("embedding")]
        if not valid_refs:
            return [], []

        parents = list(range(len(valid_refs)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for left in range(len(valid_refs)):
            for right in range(left + 1, len(valid_refs)):
                if self._cosine_distance(
                    valid_refs[left]["embedding"], valid_refs[right]["embedding"]
                ) <= self.REFERENCE_COLLISION_CLUSTER_DISTANCE:
                    union(left, right)

        cluster_refs: Dict[int, List[Dict[str, Any]]] = {}
        for index, ref in enumerate(valid_refs):
            cluster_refs.setdefault(find(index), []).append(ref)

        by_person: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}
        person_objects: Dict[str, Dict[str, Any]] = {}
        for index, ref in enumerate(valid_refs):
            key = person_key(ref["person"])
            person_objects[key] = ref["person"]
            by_person.setdefault(key, {}).setdefault(find(index), []).append(ref)

        order = [person_key(person) for person in people if person_key(person) in by_person]
        order.extend(sorted(key for key in by_person if key not in set(order)))

        historical_match_by_cluster: Dict[Tuple[str, int], Dict[str, Any]] = {}
        blocked_clusters: Dict[str, set] = {}
        for key in order:
            historical_records = list(
                person_objects[key].get("historical_identity_records") or []
            )
            if not historical_records:
                continue
            for cluster, cluster_items in by_person[key].items():
                matches: List[Optional[Dict[str, Any]]] = []
                for ref in cluster_items:
                    ref_path = Path(ref["path"])
                    if ref_path.suffix.lower() == ".cr3":
                        matches.append(self._match_historical_identity(
                            ref["embedding"],
                            historical_records,
                            format_family="cr3",
                            representation="preview",
                            processing_version=self.CR3_PREVIEW_CACHE_VARIANT,
                        ))
                        fullraw_face = ref.get("cr3_fullraw_reference_face") or {}
                        if fullraw_face.get("embedding"):
                            matches.append(self._match_historical_identity(
                                fullraw_face["embedding"],
                                historical_records,
                                format_family="cr3",
                                representation="fullraw",
                                processing_version=self.CR3_FULLRAW_CACHE_VARIANT,
                            ))
                    else:
                        matches.append(self._match_historical_identity(
                            ref["embedding"],
                            historical_records,
                            format_family="base",
                        ))
                matches = [match for match in matches if match]
                if not matches:
                    continue
                match = min(
                    matches,
                    key=lambda item: (
                        float(item["best_distance"]),
                        float(item["two_best_average"]),
                        -int(item["secure_votes"]),
                    ),
                )
                historical_match_by_cluster[(key, cluster)] = match
                blocked_clusters.setdefault(key, set()).add(cluster)

        assignments: Dict[str, int] = {}
        methods: Dict[str, str] = {}
        owner_by_cluster: Dict[int, str] = {}

        # Secure seeds: all usable candidates for this Excel row represent the
        # same face. A shared seed is left unresolved until a distinct group can
        # be found, preserving global one-to-one ownership whenever possible.
        for key in order:
            clusters = [
                cluster for cluster in by_person[key]
                if cluster not in blocked_clusters.get(key, set())
            ]
            if len(clusters) == 1 and clusters[0] not in owner_by_cluster:
                assignments[key] = clusters[0]
                owner_by_cluster[clusters[0]] = key
                methods[key] = (
                    "descarte_por_registro_historico"
                    if blocked_clusters.get(key)
                    else "grupo_facial_unico"
                )

        # Resolve crossed chains. Each newly secured owner can unlock the next
        # ambiguous Excel row; this does not depend on filename scan order.
        changed = True
        while changed:
            changed = False
            for key in order:
                if key in assignments:
                    continue
                available = [
                    cluster for cluster in by_person[key]
                    if cluster not in blocked_clusters.get(key, set())
                    if cluster not in owner_by_cluster
                ]
                if len(available) == 1:
                    cluster = available[0]
                    assignments[key] = cluster
                    owner_by_cluster[cluster] = key
                    methods[key] = "descarte_por_propiedad_facial_global"
                    changed = True

        preferred_extensions = {".jpg", ".jpeg", ".png"}

        def ref_rank(ref: Dict[str, Any]) -> Tuple[Any, ...]:
            return (
                1 if ref.get("reference_preselected") else 0,
                int(ref.get("reference_coherent_support") or 0),
                int(ref.get("reference_support_count") or 0),
                float(ref.get("reference_selection_score") or 0.0),
                1 if ref.get("reference_trusted", True) else 0,
                1 if Path(ref["path"]).suffix.lower() in preferred_extensions else 0,
                str(ref["path"]).lower(),
            )

        def cluster_rank(key: str, cluster: int) -> Tuple[Any, ...]:
            return max(ref_rank(ref) for ref in by_person[key][cluster])

        # Deterministic fallback for evidence that cannot be fully chained. The
        # user requested delivery instead of pending; exclusive unowned groups
        # are still preferred, and a shared group is used only as last resort.
        for key in order:
            if key in assignments:
                continue
            available = [
                cluster for cluster in by_person[key]
                if cluster not in blocked_clusters.get(key, set())
                if cluster not in owner_by_cluster
            ]
            allowed = [
                cluster for cluster in by_person[key]
                if cluster not in blocked_clusters.get(key, set())
            ]
            pool = available or allowed
            if not pool:
                continue
            cluster = max(pool, key=lambda item: cluster_rank(key, item))
            assignments[key] = cluster
            if cluster not in owner_by_cluster:
                owner_by_cluster[cluster] = key
                methods[key] = (
                    "desempate_post_registro_historico"
                    if blocked_clusters.get(key)
                    else "desempate_por_evidencia_y_preseleccion"
                )
            else:
                methods[key] = (
                    "respaldo_post_registro_historico"
                    if blocked_clusters.get(key)
                    else "respaldo_sin_grupo_exclusivo"
                )

        selected: List[Dict[str, Any]] = []
        audit: List[Dict[str, Any]] = []
        for key in order:
            person = person_objects[key]
            provisional = person.get("reference_path")
            chosen_cluster = assignments.get(key)
            chosen_ref = (
                max(by_person[key][chosen_cluster], key=ref_rank)
                if chosen_cluster is not None else None
            )
            if chosen_ref is not None:
                person["reference_path"] = Path(chosen_ref["path"])
                selected.append(chosen_ref)
            else:
                person["reference_path"] = None

            candidates = []
            discarded_owners = set()
            discarded_historical = []
            for cluster, refs_in_cluster in sorted(
                by_person[key].items(), key=lambda item: item[0]
            ):
                owner = owner_by_cluster.get(cluster, "")
                if cluster != chosen_cluster and owner and owner != key:
                    discarded_owners.add(owner)
                historical_match = historical_match_by_cluster.get((key, cluster))
                if historical_match:
                    discarded_historical.append(historical_match)
                for ref in sorted(refs_in_cluster, key=lambda item: str(item["path"]).lower()):
                    candidates.append({
                        "archivo": self._relative_to_workspace(Path(ref["path"])),
                        "grupo_facial": cluster,
                        "elegido": chosen_ref is not None and ref is chosen_ref,
                        "preseleccion_metadata": bool(ref.get("reference_preselected")),
                        "soporte_fotos": int(ref.get("reference_support_count") or 0),
                        "soporte_coherente": int(ref.get("reference_coherent_support") or 0),
                        "propietario_global": owner,
                        "descartado_por_historial": bool(historical_match),
                        "propietario_historico": (
                            historical_match.get("student", "")
                            if historical_match else ""
                        ),
                        "salon_historico": (
                            historical_match.get("salon", "")
                            if historical_match else ""
                        ),
                        "distancia_historica": (
                            historical_match.get("best_distance")
                            if historical_match else None
                        ),
                        "votos_historicos": (
                            historical_match.get("secure_votes", 0)
                            if historical_match else 0
                        ),
                    })

            provisional_resolved = (
                Path(provisional).resolve(strict=False) if provisional else None
            )
            chosen_resolved = (
                Path(chosen_ref["path"]).resolve(strict=False)
                if chosen_ref is not None else None
            )
            method = methods.get(
                key, "sin_candidato_nuevo_tras_descartar_historial"
            )
            historical_records = list(
                person.get("historical_identity_records") or []
            )
            resolved = chosen_ref is not None
            unique_history = {
                str(item.get("identity_id", "")): item
                for item in discarded_historical
            }
            audit.append({
                "persona": person.get("display_name", key),
                "referencia_excel": person.get("reference_value", ""),
                "candidatos_encontrados": sum(len(items) for items in by_person[key].values()),
                "grupos_faciales_encontrados": len(by_person[key]),
                "archivo_elegido": (
                    self._relative_to_workspace(Path(chosen_ref["path"]))
                    if chosen_ref is not None else "NINGUNO"
                ),
                "metodo": method,
                "resuelta": resolved,
                "codigo_repetido_historico": bool(historical_records),
                "identidades_historicas_consultadas": [
                    IdentityRegistry.public_record(record)
                    for record in historical_records
                ],
                "identidades_descartadas_por_historial": [
                    {
                        "identity_id": match.get("identity_id", ""),
                        "alumno": match.get("student", ""),
                        "salon": match.get("salon", ""),
                        "distancia": match.get("best_distance"),
                        "votos": match.get("secure_votes", 0),
                        "anclas": match.get("anchor_count", 0),
                    }
                    for match in sorted(
                        unique_history.values(),
                        key=lambda item: (
                            str(item.get("salon", "")),
                            str(item.get("student", "")),
                        ),
                    )
                ],
                "identidades_descartadas_por_propiedad": sorted(discarded_owners),
                "cambio_sobre_preseleccion": bool(
                    provisional_resolved is not None
                    and provisional_resolved != chosen_resolved
                ),
                "confianza": (
                    "alta" if method in {
                        "grupo_facial_unico",
                        "descarte_por_propiedad_facial_global",
                        "descarte_por_registro_historico",
                    }
                    else "media" if method in {
                        "desempate_por_evidencia_y_preseleccion",
                        "desempate_post_registro_historico",
                    }
                    else "bloqueada" if not resolved
                    else "baja"
                ),
                "motivo": (
                    "Todos los candidatos del codigo coinciden con identidades "
                    "confirmadas de salones anteriores; no se reutilizo una cara "
                    "historica como alumno nuevo."
                    if not resolved else ""
                ),
                "candidatos": candidates,
            })

        return selected, audit

    def _revalidate_reference_trust_after_preaudit(
        self,
        refs: List[Dict[str, Any]],
        preaudit_details: List[Dict[str, Any]],
        photo_faces_by_path: Dict[Path, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Remove stale cross-identity quarantines after candidate ownership.

        Recurrence is intentionally evaluated before the global candidate
        pre-audit. At that point, a deliberately crossed numeric candidate can
        still look like a different Excel identity and quarantine the correct
        reference. Once the pre-audit has discarded that candidate, only the
        selected official references may participate in the cross-identity
        check. All recognition thresholds and embeddings remain unchanged.
        """
        if not refs:
            return []

        high_confidence_people = {
            str(detail.get("persona", ""))
            for detail in preaudit_details
            if detail.get("confianza") == "alta"
        }
        selected_paths = {
            Path(ref["path"]).resolve(strict=False) for ref in refs
        }
        candidate_items = [
            (path, faces)
            for path, faces in photo_faces_by_path.items()
            if path.resolve(strict=False) not in selected_paths and faces
        ]
        revalidated: List[Dict[str, Any]] = []

        for ref in refs:
            if ref.get("reference_trusted", True):
                continue
            quarantine_reasons = set(ref.get("reference_quarantine_reasons") or [])
            if quarantine_reasons != {"soporte_reclamado_por_otras_identidades"}:
                continue
            if int(ref.get("ref_faces_count") or 0) != 1:
                continue

            person = ref["person"]
            display_name = str(person.get("display_name", ""))
            if display_name not in high_confidence_people:
                continue

            reference_embedding = ref.get("embedding")
            if not reference_embedding:
                continue
            support_items: List[Dict[str, Any]] = []
            for photo_path, photo_faces in candidate_items:
                matched_face = min(
                    photo_faces,
                    key=lambda item: self._cosine_distance(
                        reference_embedding, item["embedding"]
                    ),
                )
                distance = self._cosine_distance(
                    reference_embedding, matched_face["embedding"]
                )
                if distance <= self.REFERENCE_RECURRENCE_THRESHOLD:
                    support_items.append({
                        "embedding": matched_face["embedding"],
                        "path": photo_path.resolve(strict=False),
                        "distance": distance,
                    })

            support_components = self._cluster_embedding_items(
                support_items,
                max_distance=self.REFERENCE_SUPPORT_PEER_DISTANCE,
            )
            coherent_support = len(support_components[0]) if support_components else 0
            coherence_ratio = coherent_support / max(1, len(support_items))
            if (
                len(support_items) < self.REFERENCE_CONTRADICTION_MIN_SUPPORT
                or coherence_ratio < self.REFERENCE_MIN_COHERENCE_RATIO
            ):
                continue

            person_key = str(person.get("folder_name") or display_name)
            other_official_embeddings = [
                other["embedding"]
                for other in refs
                if other.get("embedding")
                and str(
                    other["person"].get("folder_name")
                    or other["person"].get("display_name", "")
                ) != person_key
            ]
            cross_claimed = 0
            for support in support_items:
                if not other_official_embeddings:
                    break
                other_distance = min(
                    self._cosine_distance(support["embedding"], embedding)
                    for embedding in other_official_embeddings
                )
                if (
                    other_distance <= self.REFERENCE_RECURRENCE_THRESHOLD
                    and float(support["distance"]) - other_distance
                    >= self.REFERENCE_CROSS_IDENTITY_MARGIN
                ):
                    cross_claimed += 1

            cross_identity_support = (
                cross_claimed >= 2
                and cross_claimed / len(support_items) >= 0.40
            )
            if cross_identity_support:
                continue

            ref["reference_trusted"] = True
            ref["reference_quarantine_reasons"] = []
            ref["reference_cross_claimed_after_preaudit"] = cross_claimed
            revalidated.append({
                "persona": display_name,
                "foto": self._relative_to_workspace(Path(ref["path"])),
                "soportes_evaluados": len(support_items),
                "soportes_coherentes": coherent_support,
                "soportes_reclamados": cross_claimed,
            })

        return revalidated

    # ------------------------------------------------------------------
    # Embedding helpers (memory + persistent disk cache)
    # ------------------------------------------------------------------

    # In-memory embedding cache: path + file stats + model + schema version.
    # Schema 2 adds facial_area, required to break recurrence ties safely.
    _EMBEDDING_CACHE_SCHEMA = 2
    _embedding_cache: Dict[tuple, Any] = {}

    @classmethod
    def _make_cache_key(cls, image_path: Path, model_name: str) -> tuple:
        """Build a cache key based on path + file stats + model so embeddings
        are reused across runs and invalidated when the file changes."""
        resolved = image_path.resolve(strict=False)
        try:
            stat = resolved.stat()
            return (
                str(resolved), stat.st_size, stat.st_mtime,
                model_name, cls._EMBEDDING_CACHE_SCHEMA,
            )
        except OSError:
            return (str(resolved), 0, 0, model_name, cls._EMBEDDING_CACHE_SCHEMA)

    def _disk_cache_path(self, cache_key: tuple) -> "Path | None":
        """Return the isolated JSON fallback path for this cache key."""
        if not self._cache_dir:
            return None
        import hashlib
        key_str = "|".join(str(k) for k in cache_key)
        digest = hashlib.sha256(key_str.encode("utf-8", errors="replace")).hexdigest()[:24]
        return self._cache_dir / f"{digest}.json"

    def _legacy_disk_cache_path(self, cache_key: tuple) -> "Path | None":
        """Return the old global cache path without ever writing to it."""
        if self._storage is None or not self._storage.legacy_cache_allowed:
            return None
        import hashlib
        key_str = "|".join(str(k) for k in cache_key)
        digest = hashlib.sha256(key_str.encode("utf-8", errors="replace")).hexdigest()[:24]
        return self._legacy_cache_dir / f"{digest}.json"

    def _load_from_disk_cache(self, cache_key: tuple) -> "list[dict] | None":
        """Load account SQLite first, then one-time legacy/fallback JSON."""
        if self._storage is not None:
            faces = self._storage.load_cached_faces(cache_key)
            if faces is not None:
                self._embedding_cache[cache_key] = faces
                return faces
            paths = [self._legacy_disk_cache_path(cache_key)]
        else:
            paths = [self._disk_cache_path(cache_key)]

        for disk_path in paths:
            if disk_path is None or not disk_path.exists():
                continue
            try:
                data = json.loads(unprotect_text(disk_path.read_text(encoding="utf-8")))
                if not isinstance(data, dict) or data.get("key") != list(cache_key):
                    continue
                faces = data.get("faces")
                if not isinstance(faces, list):
                    continue
                self._embedding_cache[cache_key] = faces
                # Import a valid legacy hit into the account database.  The
                # legacy file remains untouched for a reversible migration.
                if self._storage is not None:
                    self._storage.save_cached_faces(cache_key, faces)
                return faces
            except Exception:
                continue
        return None

    def _save_to_disk_cache(self, cache_key: tuple, faces: list) -> None:
        """Persist embeddings to the account store (JSON only as fallback)."""
        if self._storage is not None:
            self._storage.save_cached_faces(cache_key, faces)
            return
        disk_path = self._disk_cache_path(cache_key)
        if disk_path is None:
            return
        try:
            payload = {"key": list(cache_key), "faces": faces}
            protected = protect_text(json.dumps(payload, ensure_ascii=False))
            tmp_path = disk_path.with_suffix(disk_path.suffix + ".tmp")
            tmp_path.write_text(protected, encoding="utf-8")
            os.replace(tmp_path, disk_path)
        except Exception:
            pass  # Non-critical: disk cache is best-effort

    def _is_cached(self, image_path: Path, model_name: str) -> bool:
        """Check if an image is already in the memory or disk cache."""
        cache_key = self._make_cache_key(image_path, model_name)
        if cache_key in self._embedding_cache:
            return True
        if self._load_from_disk_cache(cache_key) is not None:
            return True
        return False

    # ------------------------------------------------------------------
    # CR2 (RAW) conversion — best-effort, cached, never crashes the batch
    # ------------------------------------------------------------------

    def _cr2_cache_path(self, image_path: Path) -> "Path | None":
        """Ruta del JPG cacheado para un CR2 (key: ruta + size + mtime)."""
        is_cr3 = image_path.suffix.lower() == ".cr3"
        cache_dir = self._cr3_preview_cache_dir if is_cr3 else self._cr2_cache_dir
        if not cache_dir:
            return None
        import hashlib
        key = self._make_cache_key(
            image_path,
            self.CR3_PREVIEW_CACHE_VARIANT if is_cr3 else "cr2",
        )
        key_str = "|".join(str(k) for k in key)
        digest = hashlib.sha256(key_str.encode("utf-8", errors="replace")).hexdigest()[:24]
        return cache_dir / f"{digest}.jpg"

    def _legacy_cr2_cache_path(self, image_path: Path) -> "Path | None":
        if (
            image_path.suffix.lower() == ".cr3"
            or self._storage is None
            or not self._storage.legacy_cache_allowed
        ):
            return None
        import hashlib
        key = self._make_cache_key(image_path, "cr2")
        key_str = "|".join(str(k) for k in key)
        digest = hashlib.sha256(key_str.encode("utf-8", errors="replace")).hexdigest()[:24]
        return self._legacy_cr2_cache_dir / f"{digest}.jpg"

    def _cr2_preview_cache_path(self, image_path: Path) -> "Path | None":
        is_cr3 = image_path.suffix.lower() == ".cr3"
        cache_dir = self._cr3_preview_cache_dir if is_cr3 else self._cr2_preview_cache_dir
        if not cache_dir:
            return None
        import hashlib
        key = self._make_cache_key(
            image_path,
            (
                self.CR3_INDEX_PREVIEW_CACHE_VARIANT
                if is_cr3
                else "cr2_preview_v1"
            ),
        )
        digest = hashlib.sha256(
            "|".join(str(value) for value in key).encode("utf-8", errors="replace")
        ).hexdigest()[:24]
        return cache_dir / f"{digest}.jpg"

    def _legacy_cr2_preview_cache_path(self, image_path: Path) -> "Path | None":
        if (
            image_path.suffix.lower() == ".cr3"
            or self._storage is None
            or not self._storage.legacy_cache_allowed
        ):
            return None
        import hashlib
        key = self._make_cache_key(image_path, "cr2_preview_v1")
        digest = hashlib.sha256(
            "|".join(str(value) for value in key).encode("utf-8", errors="replace")
        ).hexdigest()[:24]
        return self._legacy_cr2_preview_cache_dir / f"{digest}.jpg"

    def _cr3_fullraw_cache_path(self, image_path: Path) -> "Path | None":
        """Account-scoped JPEG cache for the CR3-only full RAW route."""
        if (
            image_path.suffix.lower() != ".cr3"
            or self._cr3_fullraw_cache_dir is None
        ):
            return None
        import hashlib
        key = self._make_cache_key(
            image_path, self.CR3_FULLRAW_CACHE_VARIANT
        )
        digest = hashlib.sha256(
            "|".join(str(value) for value in key).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:24]
        return self._cr3_fullraw_cache_dir / f"{digest}.jpg"

    def _cr3_fullraw_to_jpeg(
        self, image_path: Path
    ) -> "tuple[Path | None, str]":
        """Decode one CR3 through LibRaw at half size, independently of CR2.

        This is a second-opinion representation only.  It deliberately avoids
        ``_cr2_to_jpeg`` and ``FACESYNC_CR2_FAST`` so the proven CR2 behavior is
        unchanged and the two CR3 representations stay cache-isolated.
        """
        output = self._cr3_fullraw_cache_path(image_path)
        if output is None:
            return None, "not_cr3"
        if output.exists() and output.stat().st_size > 0:
            return output, "cache_hit"
        try:
            import rawpy
        except Exception:
            return None, "dependency"
        try:
            from PIL import Image
            with rawpy.imread(str(image_path)) as raw:
                rgb = raw.postprocess(half_size=True)
            temporary = output.with_suffix(".tmp")
            Image.fromarray(rgb).save(str(temporary), "JPEG", quality=90)
            temporary.replace(output)
            return output, "converted"
        except Exception:
            logger.exception("Fallo al revelar CR3 completo: %s", image_path)
            return None, "error"

    def _cr2_preview_to_jpeg(self, image_path: Path) -> "tuple[Path | None, str]":
        """Extract the camera JPEG preview without demosaicing the full RAW."""
        output = self._cr2_preview_cache_path(image_path)
        if output is not None and output.exists() and output.stat().st_size > 0:
            return output, "cache_hit"
        legacy_output = self._legacy_cr2_preview_cache_path(image_path)
        if (
            legacy_output is not None
            and legacy_output.exists()
            and legacy_output.stat().st_size > 0
        ):
            return legacy_output, "cache_hit"
        try:
            import rawpy
            from PIL import Image
            with rawpy.imread(str(image_path)) as raw:
                thumbnail = raw.extract_thumb()
            if output is None:
                return None, "error"
            temporary = output.with_suffix(".tmp")
            if thumbnail.format == rawpy.ThumbFormat.JPEG:
                temporary.write_bytes(thumbnail.data)
            else:
                Image.fromarray(thumbnail.data).save(str(temporary), "JPEG", quality=90)
            temporary.replace(output)
            return output, "extracted"
        except Exception:
            # Some cameras omit a useful embedded preview. Falling back to the
            # existing half-size conversion preserves coverage.
            converted, status = self._cr2_to_jpeg(image_path)
            return converted, ("full_fallback" if converted is not None else status)

    def _cr2_to_jpeg(self, image_path: Path) -> "tuple[Path | None, str]":
        """Convierte un CR2 a JPG cacheado para que DeepFace pueda leerlo.

        Devuelve (path|None, status) con status:
          'cache_hit' | 'converted' | 'dependency' | 'error'.
        NO modifica el original. Cachea en app_data/cache/cr2. Si falta rawpy
        devuelve 'dependency' (el lote continua sin tumbar nada).

        RUTA RAPIDA (FACESYNC_CR2_FAST, default ON): usa el JPEG EMBEBIDO del
        CR2 (la misma foto, generada por la camara) escalado a la MISMA
        resolucion que produce postprocess(half_size) -> los pixeles de
        decision quedan en el regimen actual, pero sin decodificar el RAW
        (~10x menos CPU y ~6x menos lectura de disco). CANDADOS: si el CR2 no
        trae preview, es mas chico que half_size, o falla cualquier cosa ->
        cae por foto a la decodificacion RAW de siempre. FACESYNC_CR2_FAST=0
        apaga la ruta rapida por completo (comportamiento identico al actual).
        """
        out = self._cr2_cache_path(image_path)
        if out is not None and out.exists() and out.stat().st_size > 0:
            return out, "cache_hit"
        legacy_out = self._legacy_cr2_cache_path(image_path)
        if legacy_out is not None and legacy_out.exists() and legacy_out.stat().st_size > 0:
            return legacy_out, "cache_hit"
        try:
            import rawpy
        except Exception:
            return None, "dependency"
        fast_mode = os.environ.get("FACESYNC_CR2_FAST", "1").strip().lower() not in (
            "0", "off", "false")
        try:
            from PIL import Image, ImageOps
            if out is None:
                return None, "error"
            with rawpy.imread(str(image_path)) as raw:
                if fast_mode:
                    try:
                        sizes = raw.sizes
                        half_w = max(1, int(sizes.width) // 2)
                        half_h = max(1, int(sizes.height) // 2)
                        thumb = raw.extract_thumb()
                        im = None
                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            import io
                            im = Image.open(io.BytesIO(thumb.data))
                            im.load()
                            # Orientacion: postprocess ya rota; el embebido trae
                            # EXIF -> aplicarlo para entregar los mismos pixeles.
                            im = ImageOps.exif_transpose(im) or im
                        elif thumb.format == rawpy.ThumbFormat.BITMAP:
                            im = Image.fromarray(thumb.data)
                        # CANDADO de calidad: el preview debe ser >= half_size
                        # en ambos ejes (aceptando ejes intercambiados por
                        # orientacion); si no, decodificacion RAW de siempre.
                        if im is not None:
                            w, h = im.size
                            ok = (w >= half_w and h >= half_h) or (
                                w >= half_h and h >= half_w)
                            if ok:
                                if im.mode != "RGB":
                                    im = im.convert("RGB")
                                tw, th = (half_w, half_h)
                                if (w >= half_h and h >= half_w) and not (
                                        w >= half_w and h >= half_h):
                                    tw, th = (half_h, half_w)
                                im = im.resize((tw, th), Image.LANCZOS)
                                im.save(str(out), "JPEG", quality=90)
                                return out, "converted"
                    except Exception:
                        # Cualquier fallo de la ruta rapida -> RAW de siempre.
                        logger.debug(
                            "CR2 fast path fallo, usando decode RAW: %s",
                            image_path, exc_info=True)
                # Ruta ORIGINAL (intacta): decodificar el RAW a half_size.
                rgb = raw.postprocess(half_size=True)
            Image.fromarray(rgb).save(str(out), "JPEG", quality=90)
            return out, "converted"
        except Exception:
            logger.exception("Fallo al convertir CR2: %s", image_path)
            return None, "error"

    def _get_all_face_embeddings(
        self,
        image_path: Path,
        *,
        model_name: str,
        detector_backend: str,
        DeepFace: Any,
        cr2_metrics: Optional[Dict[str, int]] = None,
        cache_variant: str = "",
        decode_path_override: Optional[Path] = None,
    ) -> "list[dict] | None":
        """Extract embeddings for ALL faces in an image.

        Returns list of dicts with 'embedding' and 'face_confidence' keys,
        or None if the image cannot be processed at all.
        Uses two-tier cache: in-memory first, then persistent disk.
        """
        effective_variant = cache_variant
        if not effective_variant and image_path.suffix.lower() == ".cr3":
            effective_variant = self.CR3_PREVIEW_CACHE_VARIANT
        cache_model_name = (
            f"{model_name}:{effective_variant}" if effective_variant else model_name
        )
        cache_key = self._make_cache_key(image_path, cache_model_name)

        # Tier 1: in-memory cache
        cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            return cached

        # Tier 2: persistent disk cache
        disk_cached = self._load_from_disk_cache(cache_key)
        if disk_cached is not None:
            return disk_cached

        # RAW (CR2/CR3): convertir (cacheado) a JPG antes de DeepFace.
        # JPG/PNG van directo. El motor facial y sus parametros no cambian.
        decode_path = decode_path_override or image_path
        if decode_path_override is None and image_path.suffix.lower() in self.RAW_EXTENSIONS:
            converted, status = self._cr2_to_jpeg(image_path)
            self._record_raw_status(cr2_metrics, image_path, status)
            if converted is None:
                return None  # no se cachea el fallo: reintenta si instalan rawpy
            decode_path = converted

        # Tier 3: compute via DeepFace. ONNX/DirectML uses the same DeepFace
        # pre/post-processing. If the GPU driver rejects a workload, restore
        # TensorFlow and retry this exact image once.
        def represent_faces():
            return DeepFace.represent(
                img_path=str(decode_path),
                model_name=model_name,
                detector_backend=detector_backend,
                enforce_detection=False,
            )

        try:
            try:
                results = represent_faces()
            except Exception:
                if self._gpu_backend is None:
                    raise
                self._performance_stats["gpu_fallbacks"] = (
                    int(self._performance_stats.get("gpu_fallbacks", 0)) + 1
                )
                self._performance_stats["backend"] = "deepface_tensorflow_fallback"
                self._disable_gpu_backend()
                results = represent_faces()
            if not results or not isinstance(results, list):
                self._embedding_cache[cache_key] = []
                self._save_to_disk_cache(cache_key, [])
                return []
            faces = []
            for item in results:
                emb = item.get("embedding")
                if emb:
                    faces.append({
                        "embedding": emb,
                        "face_confidence": float(item.get("face_confidence", 0.0)),
                        "facial_area": dict(item.get("facial_area") or {}),
                    })
            self._embedding_cache[cache_key] = faces
            self._save_to_disk_cache(cache_key, faces)
            return faces
        except Exception:
            return None

    @staticmethod
    def _normalize_deepface_faces(results: Any) -> List[Dict[str, Any]]:
        """Normalize DeepFace output without changing embedding values."""
        if not results or not isinstance(results, list):
            return []
        faces: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            embedding = item.get("embedding")
            if embedding:
                faces.append({
                    "embedding": embedding,
                    "face_confidence": float(item.get("face_confidence", 0.0)),
                    "facial_area": dict(item.get("facial_area") or {}),
                })
        return faces

    @staticmethod
    def _facial_area_iou(left: Dict[str, Any], right: Dict[str, Any]) -> float:
        """Intersection-over-union for two DeepFace facial-area dictionaries."""
        try:
            lx, ly = float(left.get("x", 0)), float(left.get("y", 0))
            lw, lh = float(left.get("w", 0)), float(left.get("h", 0))
            rx, ry = float(right.get("x", 0)), float(right.get("y", 0))
            rw, rh = float(right.get("w", 0)), float(right.get("h", 0))
        except (TypeError, ValueError):
            return 0.0
        if min(lw, lh, rw, rh) <= 0:
            return 0.0
        x1, y1 = max(lx, rx), max(ly, ry)
        x2, y2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
        intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        union = lw * lh + rw * rh - intersection
        return intersection / union if union > 0 else 0.0

    def _strengthen_cr3_references(
        self,
        *,
        refs_with_embeddings: List[Dict[str, Any]],
        photo_faces_by_path: Dict[Path, List[Dict[str, Any]]],
        image_paths: List[Path],
        model_name: str,
        detector_backend: str,
        DeepFace: Any,
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Fortalece referencias CR3 sin cambiar la ruta JPG/CR2.

        La foto/codigo raiz sigue siendo la autoridad. El selector puede elegir
        una sola cara operativa respaldada por recurrencia; nunca crea una
        galeria ni combina embeddings entre preview y Full RAW.
        """
        started = time.perf_counter()
        cr3_refs = [
            ref for ref in refs_with_embeddings
            if Path(ref.get("path", "")).suffix.lower() == ".cr3"
        ]
        stats: Dict[str, Any] = {
            "enabled": bool(cr3_refs),
            "references": len(cr3_refs),
            "cr3_photos": 0,
            "preview_sizes": 0,
            "fullraw_processed": 0,
            "fullraw_cache_hits": 0,
            "fullraw_converted": 0,
            "fullraw_errors": 0,
            "promoted_references": 0,
            "preserved_references": len(cr3_refs),
        }
        if not cr3_refs:
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return [], stats

        preview_faces_by_resolved = {
            Path(path).resolve(strict=False): list(faces)
            for path, faces in (photo_faces_by_path or {}).items()
            if Path(path).suffix.lower() == ".cr3"
        }
        for ref in cr3_refs:
            resolved = Path(ref["path"]).resolve(strict=False)
            preview_faces_by_resolved.setdefault(
                resolved, list(ref.get("candidate_faces") or [])
            )

        path_by_resolved: Dict[Path, Path] = {}
        for path in [Path(ref["path"]) for ref in cr3_refs] + [
            Path(path) for path in image_paths if Path(path).suffix.lower() == ".cr3"
        ]:
            path_by_resolved.setdefault(path.resolve(strict=False), path)
        stats["cr3_photos"] = len(path_by_resolved)

        # Full RAW se limita a una union amplia de candidatos por rostro raiz.
        # Conserva O(referencias * fotos) y evita revelar 10,000 CR3 cuando cada
        # alumno sólo necesita decenas de candidatos para escoger una referencia.
        candidate_limit = max(30, self.GALLERY_MAX_PER_PERSON * 2)
        selected_resolved = {
            Path(ref["path"]).resolve(strict=False) for ref in cr3_refs
        }
        reference_resolved = set(selected_resolved)
        for ref in cr3_refs:
            ref_faces = list(ref.get("candidate_faces") or [])
            for ref_face in ref_faces:
                ref_embedding = ref_face.get("embedding")
                if not ref_embedding:
                    continue
                scored: List[Tuple[float, str, Path]] = []
                for resolved, faces in preview_faces_by_resolved.items():
                    if resolved in reference_resolved or not faces:
                        continue
                    distances = [
                        self._cosine_distance(ref_embedding, face["embedding"])
                        for face in faces if face.get("embedding")
                    ]
                    if not distances:
                        continue
                    best_distance = min(distances)
                    scored.append((best_distance, str(resolved).casefold(), resolved))
                selected_resolved.update(
                    item[2] for item in sorted(scored)[:candidate_limit]
                )
        cr3_paths = [
            path_by_resolved[resolved]
            for resolved in sorted(selected_resolved, key=lambda path: str(path).casefold())
            if resolved in path_by_resolved
        ]
        stats["candidate_limit_per_reference_face"] = candidate_limit
        stats["candidate_photos"] = len(cr3_paths)

        preview_faces: Dict[Path, List[Dict[str, Any]]] = {}
        fullraw_faces: Dict[Path, List[Dict[str, Any]]] = {}
        preview_sizes: Dict[Path, Tuple[int, int]] = {}
        fullraw_sizes: Dict[Path, Tuple[int, int]] = {}

        try:
            from PIL import Image
            from tools.cr3_reference_selector import select_cr3_reference_evidence

            for path in cr3_paths:
                if cancel_event is not None and cancel_event.is_set():
                    raise _FaceSyncCancelled()
                resolved = path.resolve(strict=False)
                route_preview_faces = preview_faces_by_resolved.get(resolved) or []
                if route_preview_faces:
                    preview_faces[path] = route_preview_faces

                preview_decode, _preview_status = self._cr2_to_jpeg(path)
                if preview_decode is not None:
                    try:
                        with Image.open(preview_decode) as image:
                            preview_sizes[path] = tuple(image.size)
                        stats["preview_sizes"] += 1
                    except Exception:
                        logger.debug(
                            "No se pudo medir el preview CR3: %s", path,
                            exc_info=True,
                        )

                decoded, status = self._cr3_fullraw_to_jpeg(path)
                if status == "cache_hit":
                    stats["fullraw_cache_hits"] += 1
                elif status == "converted":
                    stats["fullraw_converted"] += 1
                if decoded is None:
                    stats["fullraw_errors"] += 1
                    continue
                try:
                    with Image.open(decoded) as image:
                        fullraw_sizes[path] = tuple(image.size)
                except Exception:
                    stats["fullraw_errors"] += 1
                    continue
                route_fullraw_faces = self._get_all_face_embeddings(
                    path,
                    model_name=model_name,
                    detector_backend=detector_backend,
                    DeepFace=DeepFace,
                    cache_variant=self.CR3_FULLRAW_CACHE_VARIANT,
                    decode_path_override=decoded,
                )
                if route_fullraw_faces is None:
                    stats["fullraw_errors"] += 1
                    continue
                fullraw_faces[path] = list(route_fullraw_faces)
                stats["fullraw_processed"] += 1

            selections, diagnostics = select_cr3_reference_evidence(
                cr3_refs,
                preview_faces,
                fullraw_faces,
                preview_sizes,
                fullraw_sizes,
                cosine_distance=self._cosine_distance,
                recurrence_threshold=self.REFERENCE_RECURRENCE_THRESHOLD,
                peer_distance=self.REFERENCE_SUPPORT_PEER_DISTANCE,
                identity_margin=self.REFERENCE_CROSS_IDENTITY_MARGIN,
                geometry_min_iou=self.CR3_CROSS_ROUTE_FACE_IOU,
                geometry_min_margin=self.IDENTITY_CONFLICT_MARGIN,
                min_support=self.HISTORICAL_IDENTITY_MIN_SUPPORT,
                min_face_side_pixels=self.REFERENCE_MIN_FACE_SIDE_PIXELS,
            )

            for selection in selections:
                ref = selection["reference"]
                preview_face = selection.get("preview_face")
                fullraw_face = selection.get("fullraw_face")
                if preview_face is not None:
                    ref["cr3_preview_reference_face"] = preview_face
                if fullraw_face is not None:
                    ref["cr3_fullraw_reference_face"] = fullraw_face
                ref["cr3_reference_anchor_path"] = selection.get("anchor_path")
                ref["cr3_reference_selected_route"] = selection.get("selected_route")
                ref["cr3_reference_promoted"] = bool(selection.get("promoted"))
                if selection.get("promoted") and preview_face is not None:
                    ref["cr3_original_candidate_faces"] = list(
                        ref.get("candidate_faces") or []
                    )
                    ref["candidate_faces"] = [preview_face]

            stats["promoted_references"] = sum(
                bool(selection.get("promoted")) for selection in selections
            )
            stats["preserved_references"] = len(cr3_refs) - stats["promoted_references"]

            for detail in diagnostics:
                for key in ("foto_raiz", "foto_ancla"):
                    value = detail.get(key)
                    if value:
                        detail[key] = self._relative_to_workspace(Path(value))
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return diagnostics, stats
        except _FaceSyncCancelled:
            raise
        except Exception as exc:
            logger.exception("Fallo el selector CR3; se conservan las referencias base")
            stats["error"] = f"{type(exc).__name__}: {exc}"
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return [], stats

    def _bootstrap_cr3_gallery_route(
        self,
        *,
        route: str,
        refs_with_embeddings: List[Dict[str, Any]],
        photo_faces: Dict[Path, List[Dict[str, Any]]],
        gallery_data: Dict[str, Dict[str, Any]],
        match_map: Dict[Path, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Alimenta una galeria solo con grupos CR3 previamente validados."""
        started = time.perf_counter()
        cr3_refs = [
            ref for ref in refs_with_embeddings or []
            if Path(ref.get("path", "")).suffix.lower() == ".cr3"
        ]
        empty_stats: Dict[str, Any] = {
            "enabled": bool(cr3_refs),
            "route": route,
            "references": len(cr3_refs),
            "feeders": 0,
            "matches_added": 0,
        }
        if not cr3_refs:
            empty_stats["seconds"] = round(time.perf_counter() - started, 3)
            return [], empty_stats

        try:
            from tools.cr3_gallery_bootstrap import build_cr3_gallery_bootstrap

            proposals, diagnostics, stats = build_cr3_gallery_bootstrap(
                cr3_refs,
                photo_faces,
                gallery_data,
                route=route,
                cosine_distance=self._cosine_distance,
                secure_threshold=self.THRESHOLD_SECURE,
                review_threshold=self.THRESHOLD_REVIEW,
                identity_margin=self.REFERENCE_CROSS_IDENTITY_MARGIN,
                min_support=max(2, self.HISTORICAL_IDENTITY_MIN_SUPPORT),
                max_anchors=self.GALLERY_MAX_PER_PERSON,
                duplicate_threshold=self.GALLERY_DUPLICATE_THRESHOLD,
                candidate_limit=max(30, self.GALLERY_MAX_PER_PERSON * 2),
            )

            entries_added = 0
            matches_added = 0
            for folder, proposal in proposals.items():
                gallery = gallery_data.get(folder)
                if not gallery:
                    continue
                for anchor in proposal.get("anchors") or []:
                    anchor_path = Path(anchor["path"]).resolve(strict=False)
                    if anchor_path in gallery.get("paths", []):
                        continue
                    gallery.setdefault("embeddings", []).append(anchor["embedding"])
                    gallery.setdefault("paths", []).append(anchor_path)
                    try:
                        anchor_time = float(anchor_path.stat().st_mtime)
                    except OSError:
                        anchor_time = 0.0
                    gallery.setdefault("times", []).append(anchor_time)
                    gallery.setdefault("cluster_members", set()).add(
                        (anchor_path, int(anchor["face_index"]))
                    )
                    entries_added += 1

                for decision in proposal.get("decisions") or []:
                    image_path = Path(decision["path"]).resolve(strict=False)
                    face_index = int(decision["face_index"])
                    existing = [
                        match for match in match_map.get(image_path, [])
                        if str(match["person"].get("folder_name")) == folder
                        and int(match.get("face_index", 0)) == face_index
                    ]
                    decision_distance = float(decision["distance"])
                    if existing and min(
                        float(match.get("distance", 999)) for match in existing
                    ) <= decision_distance:
                        continue
                    match_map.setdefault(image_path, []).append({
                        "person": proposal["reference"]["person"],
                        "distance": decision_distance,
                        "verified": True,
                        "face_index": face_index,
                        "match_type": "secure",
                        "match_source": f"cr3_gallery_bootstrap_{route}",
                        "bootstrap_reason": decision["reason"],
                        "bootstrap_supporters": int(decision["supporter_count"]),
                        "bootstrap_identity_margin": decision.get("identity_margin"),
                    })
                    matches_added += 1

            for detail in diagnostics:
                root = detail.get("foto_raiz")
                if root:
                    detail["foto_raiz"] = self._relative_to_workspace(Path(root))
                for key in ("alimentadores", "fotos_reevaluadas"):
                    detail[key] = [
                        self._relative_to_workspace(Path(path))
                        for path in detail.get(key) or []
                    ]
            stats["entries_added"] = entries_added
            stats["matches_added"] = matches_added
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return diagnostics, stats
        except Exception as exc:
            logger.exception(
                "Fallo el arranque de galeria CR3 %s; se conserva la galeria base",
                route,
            )
            empty_stats["error"] = f"{type(exc).__name__}: {exc}"
            empty_stats["seconds"] = round(time.perf_counter() - started, 3)
            return [], empty_stats

    def _recover_cr3_fullraw_assignments(
        self,
        *,
        image_paths: List[Path],
        refs_with_embeddings: List[Dict[str, Any]],
        base_match_map: Dict[Path, List[Dict[str, Any]]],
        base_photo_faces: Dict[Path, List[Dict[str, Any]]],
        base_confirmed: Dict[Path, List[Dict[str, Any]]],
        base_conflicts: Optional[List[Dict[str, Any]]] = None,
        base_rescues: Optional[List[Dict[str, Any]]] = None,
        model_name: str,
        detector_backend: str,
        ambiguity_margin: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[
        Dict[Path, List[Dict[str, Any]]],
        List[Dict[str, Any]],
        Dict[str, Any],
    ]:
        """CR3-only second opinion after the validated motor has decided.

        The first-pass result is immutable.  Full-RAW evidence can only add an
        identity for a CR3 face that was not already securely owned.  It uses a
        separate reference/candidate representation, its own gallery and all
        existing thresholds.  CR2 and non-RAW images are never admitted here.
        """
        started = time.perf_counter()
        enabled = self.CR3_DUAL_DECODE_ENABLED and os.environ.get(
            "FACESYNC_CR3_DUAL", "1"
        ).strip().lower() not in {"0", "off", "false"}
        cr3_paths = [
            path for path in image_paths if path.suffix.lower() == ".cr3"
        ]
        stats: Dict[str, Any] = {
            "enabled": bool(enabled and cr3_paths),
            "cr3_photos": len(cr3_paths),
            "targets": 0,
            "feeders": 0,
            "fullraw_processed": 0,
            "fullraw_cache_hits": 0,
            "fullraw_converted": 0,
            "fullraw_errors": 0,
            "embedding_cache_hits": 0,
            "embedding_cache_misses": 0,
            "recovered_photos": 0,
            "recovered_assignments": 0,
            "blocked_cross_route_conflicts": 0,
            "route_arbiter": {"enabled": False},
        }
        if not stats["enabled"] or not refs_with_embeddings:
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return {}, [], stats

        def resolved_map(mapping: Dict[Path, Any]) -> Dict[Path, Any]:
            return {
                Path(path).resolve(strict=False): value
                for path, value in (mapping or {}).items()
            }

        matches_by_resolved = resolved_map(base_match_map)
        faces_by_resolved = resolved_map(base_photo_faces)
        confirmed_by_resolved = resolved_map(base_confirmed)
        path_by_resolved = {
            path.resolve(strict=False): path for path in cr3_paths
        }

        # A target is a CR3 that has no final owner, contains review evidence,
        # or contains at least one detected face without a direct secure owner.
        target_resolved: set[Path] = set()
        for path in cr3_paths:
            resolved = path.resolve(strict=False)
            matches = list(matches_by_resolved.get(resolved) or [])
            faces = list(faces_by_resolved.get(resolved) or [])
            confirmed_people = list(confirmed_by_resolved.get(resolved) or [])
            secure_face_indices = {
                int(match.get("face_index", 0))
                for match in matches
                if float(match.get("distance", 999)) <= self.THRESHOLD_SECURE
            }
            has_review = any(
                self.THRESHOLD_SECURE
                < float(match.get("distance", 999))
                <= self.THRESHOLD_REVIEW
                for match in matches
            )
            if (
                not confirmed_people
                or has_review
                or len(secure_face_indices) < len(faces)
            ):
                target_resolved.add(resolved)

        # Full-RAW galleries need a few already-safe examples.  Select only the
        # strongest first-pass CR3 evidence, capped by the existing gallery size.
        feeder_candidates: Dict[str, List[Tuple[float, Path]]] = {}
        for path, matches in (base_match_map or {}).items():
            if Path(path).suffix.lower() != ".cr3":
                continue
            resolved = Path(path).resolve(strict=False)
            confirmed_folders = {
                person.get("folder_name")
                for person in (confirmed_by_resolved.get(resolved) or [])
            }
            for match in matches:
                folder = match["person"].get("folder_name")
                distance = float(match.get("distance", 999))
                if folder in confirmed_folders and distance <= self.THRESHOLD_SECURE:
                    feeder_candidates.setdefault(str(folder), []).append(
                        (distance, path_by_resolved.get(resolved, Path(path)))
                    )
        feeder_resolved: set[Path] = set()
        feeder_limit = min(
            self.CR3_FALLBACK_FEEDERS_PER_IDENTITY,
            self.GALLERY_MAX_PER_PERSON,
        )
        for candidates in feeder_candidates.values():
            seen: set[Path] = set()
            for _distance, path in sorted(
                candidates, key=lambda item: (item[0], str(item[1]).lower())
            ):
                resolved = Path(path).resolve(strict=False)
                if resolved in seen:
                    continue
                seen.add(resolved)
                feeder_resolved.add(resolved)
                if len(seen) >= feeder_limit:
                    break

        reference_cr3_resolved = {
            Path(ref["path"]).resolve(strict=False)
            for ref in refs_with_embeddings
            if Path(ref["path"]).suffix.lower() == ".cr3"
        }
        work_resolved = (
            target_resolved | feeder_resolved | reference_cr3_resolved
        )
        work_paths = [
            path for path in cr3_paths
            if path.resolve(strict=False) in work_resolved
        ]
        stats["targets"] = len(target_resolved)
        stats["feeders"] = len(feeder_resolved - target_resolved)
        stats["work_photos"] = len(work_paths)

        try:
            from deepface import DeepFace
        except Exception as exc:
            stats["error"] = f"DeepFace: {type(exc).__name__}: {exc}"
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return {}, [], stats

        full_faces_by_resolved: Dict[Path, List[Dict[str, Any]]] = {}
        full_sizes_by_resolved: Dict[Path, Tuple[int, int]] = {}
        preview_sizes_by_resolved: Dict[Path, Tuple[int, int]] = {}

        def full_faces(path: Path) -> Optional[List[Dict[str, Any]]]:
            resolved = path.resolve(strict=False)
            if resolved in full_faces_by_resolved:
                return full_faces_by_resolved[resolved]
            if cancel_event is not None and cancel_event.is_set():
                raise _FaceSyncCancelled()
            cache_model = f"{model_name}:{self.CR3_FULLRAW_CACHE_VARIANT}"
            embedding_was_cached = self._is_cached(path, cache_model)
            decoded, status = self._cr3_fullraw_to_jpeg(path)
            if status == "cache_hit":
                stats["fullraw_cache_hits"] += 1
            elif status == "converted":
                stats["fullraw_converted"] += 1
            elif decoded is None:
                stats["fullraw_errors"] += 1
                return None
            if decoded is None:
                stats["fullraw_errors"] += 1
                return None
            try:
                from PIL import Image

                with Image.open(decoded) as image:
                    full_sizes_by_resolved[resolved] = tuple(image.size)
            except Exception:
                # Sin geometria medible, el arbitro solo admitira el caso
                # inequívoco de un rostro real exclusivo de Full RAW.
                pass
            faces = self._get_all_face_embeddings(
                path,
                model_name=model_name,
                detector_backend=detector_backend,
                DeepFace=DeepFace,
                cache_variant=self.CR3_FULLRAW_CACHE_VARIANT,
                decode_path_override=decoded,
            )
            if faces is None:
                stats["fullraw_errors"] += 1
                return None
            if embedding_was_cached:
                stats["embedding_cache_hits"] += 1
            else:
                stats["embedding_cache_misses"] += 1
            stats["fullraw_processed"] += 1
            full_faces_by_resolved[resolved] = list(faces)
            return full_faces_by_resolved[resolved]

        self._enable_gpu_backend(model_name, detector_backend)
        try:
            # Rebuild only the selected reference face in the full-RAW space.
            full_refs: List[Dict[str, Any]] = []
            for ref in refs_with_embeddings:
                ref_path = Path(ref["path"])
                if ref_path.suffix.lower() != ".cr3":
                    full_refs.append(dict(ref))
                    continue
                candidates = full_faces(ref_path)
                if not candidates:
                    stats.setdefault("invalid_fullraw_references", []).append(
                        self._relative_to_workspace(ref_path)
                    )
                    continue
                selected_face = ref.get("cr3_fullraw_reference_face")
                if not selected_face:
                    # Compatibilidad exacta con referencias CR3 que no fueron
                    # fortalecidas: conserva la seleccion anterior por cercania.
                    selected_face = min(
                        candidates,
                        key=lambda face: self._cosine_distance(
                            ref["embedding"], face["embedding"]
                        ),
                    )
                full_ref = dict(ref)
                full_ref["embedding"] = selected_face["embedding"]
                full_ref["embeddings"] = [selected_face["embedding"]]
                full_ref["candidate_faces"] = [selected_face]
                full_refs.append(full_ref)

            if not full_refs:
                stats["error"] = "No hubo referencias utilizables en la ruta CR3 completa."
                stats["seconds"] = round(time.perf_counter() - started, 3)
                return {}, [], stats

            for path in work_paths:
                full_faces(path)

            # Mide la misma representacion preview que produjo la primera
            # decision. No recalcula embeddings y no mezcla espacios.
            try:
                from PIL import Image

                for path in work_paths:
                    resolved = path.resolve(strict=False)
                    decoded, _status = self._cr2_to_jpeg(path)
                    if decoded is None:
                        continue
                    try:
                        with Image.open(decoded) as image:
                            preview_sizes_by_resolved[resolved] = tuple(image.size)
                    except Exception:
                        continue
            except Exception:
                pass

            full_match_map: Dict[Path, List[Dict[str, Any]]] = {}
            full_embedding_map: Dict[Path, List[list]] = {}
            refs_by_resolved: Dict[Path, List[Dict[str, Any]]] = {}
            for ref in full_refs:
                refs_by_resolved.setdefault(
                    Path(ref["path"]).resolve(strict=False), []
                ).append(ref)

            for path in work_paths:
                resolved = path.resolve(strict=False)
                faces = full_faces_by_resolved.get(resolved) or []
                if not faces:
                    continue
                full_embedding_map[path] = [face["embedding"] for face in faces]
                if resolved in refs_by_resolved:
                    for ref in refs_by_resolved[resolved]:
                        full_match_map.setdefault(path, []).append({
                            "person": ref["person"],
                            "distance": 0.0,
                            "verified": True,
                            "face_index": 0,
                            "match_type": "secure",
                            "match_source": self.CR3_FULLRAW_CACHE_VARIANT,
                        })
                    continue
                for face_index, face in enumerate(faces):
                    best_by_person: Dict[str, Tuple[Dict[str, Any], float]] = {}
                    for ref in full_refs:
                        folder = str(ref["person"]["folder_name"])
                        distance = self._cosine_distance(
                            face["embedding"], ref["embedding"]
                        )
                        previous = best_by_person.get(folder)
                        if previous is None or distance < previous[1]:
                            best_by_person[folder] = (ref, distance)
                    for ref, distance in best_by_person.values():
                        if distance > self.THRESHOLD_REVIEW:
                            continue
                        full_match_map.setdefault(path, []).append({
                            "person": ref["person"],
                            "distance": distance,
                            "verified": distance <= self.THRESHOLD_SECURE,
                            "face_index": face_index,
                            "match_type": (
                                "secure"
                                if distance <= self.THRESHOLD_SECURE
                                else "review"
                            ),
                            "faces_in_photo": len(faces),
                            "match_source": self.CR3_FULLRAW_CACHE_VARIANT,
                        })

            full_gallery, full_gallery_stats = self._build_identity_gallery(
                full_refs, full_match_map, full_embedding_map
            )
            full_bootstrap_details, full_bootstrap_stats = (
                self._bootstrap_cr3_gallery_route(
                    route="fullraw",
                    refs_with_embeddings=full_refs,
                    photo_faces=full_faces_by_resolved,
                    gallery_data=full_gallery,
                    match_map=full_match_map,
                )
            )
            full_gallery_stats["total_gallery_entries"] = sum(
                len(gallery.get("embeddings") or [])
                for gallery in full_gallery.values()
            )
            (
                full_confirmed,
                full_review,
                full_conflicts,
                full_rescues,
            ) = self._resolve_assignments(
                full_match_map,
                ambiguity_margin=ambiguity_margin,
                gallery_data=full_gallery,
                photo_face_embeddings=full_embedding_map,
            )
            stats["gallery_stats"] = full_gallery_stats
            stats["gallery_bootstrap"] = full_bootstrap_stats
            stats["gallery_bootstrap_details"] = full_bootstrap_details
            stats["full_route_review"] = len(full_review)
            stats["full_route_conflicts"] = len(full_conflicts)
            from tools.cr3_route_arbiter import arbitrate_cr3_routes

            target_paths = [
                path_by_resolved[resolved]
                for resolved in sorted(target_resolved, key=lambda item: str(item).casefold())
                if resolved in path_by_resolved
            ]
            accepted, arbitration_details, arbitration_stats = (
                arbitrate_cr3_routes(
                    image_paths=target_paths,
                    preview_matches=base_match_map,
                    preview_faces=base_photo_faces,
                    preview_sizes=preview_sizes_by_resolved,
                    preview_confirmed=base_confirmed,
                    preview_conflicts=base_conflicts,
                    preview_rescues=base_rescues,
                    fullraw_matches=full_match_map,
                    fullraw_faces=full_faces_by_resolved,
                    fullraw_sizes=full_sizes_by_resolved,
                    fullraw_confirmed=full_confirmed,
                    fullraw_conflicts=full_conflicts,
                    fullraw_rescues=full_rescues,
                    secure_threshold=self.THRESHOLD_SECURE,
                    review_threshold=self.THRESHOLD_REVIEW,
                    identity_margin=self.IDENTITY_GALLERY_MARGIN,
                    geometry_min_iou=self.CR3_CROSS_ROUTE_FACE_IOU,
                    geometry_min_margin=self.REFERENCE_CROSS_IDENTITY_MARGIN,
                    min_gallery_support=self.GALLERY_RESCUE_MIN_SUPPORTERS,
                )
            )
            additions: Dict[Path, List[Dict[str, Any]]] = {}
            details: List[Dict[str, Any]] = []
            for decision in accepted:
                resolved = Path(decision["path"]).resolve(strict=False)
                original_path = path_by_resolved.get(resolved, Path(decision["path"]))
                person = dict(decision["person"])
                folder = str(person.get("folder_name"))
                existing_folders = {
                    str(existing.get("folder_name"))
                    for existing in (confirmed_by_resolved.get(resolved) or [])
                }
                if folder in existing_folders:
                    continue
                additions.setdefault(original_path, []).append(person)
                details.append({
                    "foto": self._relative_to_workspace(original_path),
                    "alumno": person.get("display_name", ""),
                    "distancia_fullraw": round(float(decision["distance"]), 4),
                    "metodo": decision["reason"],
                    "margen_identidad_fullraw": (
                        round(float(decision["identity_margin"]), 4)
                        if decision.get("identity_margin") is not None else None
                    ),
                    "soportes_galeria": int(decision.get("gallery_supporters", 0)),
                    "fuente_fullraw": decision.get("match_source", ""),
                    "rostro_preview": (
                        int(decision["preview_face_index"]) + 1
                        if decision.get("preview_face_index") is not None else None
                    ),
                    "rostro_fullraw": int(decision["fullraw_face_index"]) + 1,
                })

            for detail in arbitration_details:
                detail["foto"] = self._relative_to_workspace(Path(detail["foto"]))
            stats["route_arbiter"] = arbitration_stats
            stats["route_arbiter_details"] = arbitration_details
            stats["blocked_cross_route_conflicts"] = int(
                arbitration_stats.get("blocked_contradictions", 0)
            )

            stats["recovered_photos"] = len(additions)
            stats["recovered_assignments"] = sum(
                len(persons) for persons in additions.values()
            )
            cr3_full_refs = [
                ref for ref in full_refs
                if Path(ref.get("path", "")).suffix.lower() == ".cr3"
            ]
            cr3_folders = {
                str((ref.get("person") or {}).get("folder_name", ""))
                for ref in cr3_full_refs
            }
            self._cr3_fullraw_registry_evidence = {
                "refs": cr3_full_refs,
                "gallery": {
                    folder: gallery
                    for folder, gallery in full_gallery.items()
                    if folder in cr3_folders
                },
            }
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return additions, details, stats
        except _FaceSyncCancelled:
            raise
        except Exception as exc:
            logger.exception("La segunda oportunidad CR3 fallo; se conserva la base")
            stats["error"] = f"{type(exc).__name__}: {exc}"
            stats["seconds"] = round(time.perf_counter() - started, 3)
            return {}, [], stats
        finally:
            self._disable_gpu_backend()

    def _get_preview_embeddings_batch(
        self,
        items: List[Tuple[Path, Path]],
        *,
        model_name: str,
        detector_backend: str,
        DeepFace: Any,
        metrics: Optional[Dict[str, int]] = None,
    ) -> Dict[Path, Optional[List[Dict[str, Any]]]]:
        """Batch only the cheap preview pass; final motor remains scalar.

        DeepFace 0.0.100 preserves per-image RetinaFace preprocessing while
        collecting the resulting 112x112 crops into one ArcFace forward pass.
        Any batch-level problem falls back to the original per-image helper.
        """
        output: Dict[Path, Optional[List[Dict[str, Any]]]] = {}
        misses: List[Tuple[Path, Path, tuple, str]] = []
        metrics = metrics if metrics is not None else {}

        for image_path, preview_path in items:
            cache_variant = (
                self.CR3_INDEX_PREVIEW_CACHE_VARIANT
                if image_path.suffix.lower() == ".cr3"
                else "cr2_preview_v1"
            )
            cache_model_name = f"{model_name}:{cache_variant}"
            cache_key = self._make_cache_key(image_path, cache_model_name)
            cached = self._embedding_cache.get(cache_key)
            if cached is None:
                cached = self._load_from_disk_cache(cache_key)
            if cached is not None:
                output[image_path] = cached
                metrics["preview_cache_hits"] = metrics.get("preview_cache_hits", 0) + 1
            else:
                misses.append((image_path, preview_path, cache_key, cache_variant))
                metrics["preview_cache_misses"] = metrics.get("preview_cache_misses", 0) + 1

        if not misses:
            return output
        if len(misses) == 1:
            image_path, preview_path, _cache_key, cache_variant = misses[0]
            output[image_path] = self._get_all_face_embeddings(
                image_path,
                model_name=model_name,
                detector_backend=detector_backend,
                DeepFace=DeepFace,
                cache_variant=cache_variant,
                decode_path_override=preview_path,
            )
            return output

        try:
            batch_results = DeepFace.represent(
                img_path=[
                    str(preview_path)
                    for _image_path, preview_path, _key, _variant in misses
                ],
                model_name=model_name,
                detector_backend=detector_backend,
                enforce_detection=False,
            )
            if not isinstance(batch_results, list) or len(batch_results) != len(misses):
                raise RuntimeError("DeepFace devolvio un lote con longitud inesperada")
            metrics["arcface_batch_calls"] = metrics.get("arcface_batch_calls", 0) + 1
            metrics["arcface_batched_images"] = (
                metrics.get("arcface_batched_images", 0) + len(misses)
            )
            for (
                image_path,
                _preview_path,
                cache_key,
                _cache_variant,
            ), result in zip(misses, batch_results):
                faces = self._normalize_deepface_faces(result)
                self._embedding_cache[cache_key] = faces
                self._save_to_disk_cache(cache_key, faces)
                output[image_path] = faces
            return output
        except Exception:
            metrics["arcface_batch_fallbacks"] = (
                metrics.get("arcface_batch_fallbacks", 0) + 1
            )
            for image_path, preview_path, _cache_key, cache_variant in misses:
                output[image_path] = self._get_all_face_embeddings(
                    image_path,
                    model_name=model_name,
                    detector_backend=detector_backend,
                    DeepFace=DeepFace,
                    cache_variant=cache_variant,
                    decode_path_override=preview_path,
                )
            return output

    @staticmethod
    def _cosine_distance(emb_a: list, emb_b: list) -> float:
        """Compute cosine distance between two embedding vectors.
        Uses numpy if available, falls back to pure Python."""
        try:
            import numpy as np
            a = np.asarray(emb_a, dtype=np.float64)
            b = np.asarray(emb_b, dtype=np.float64)
            dot = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 999.0
            return float(1.0 - (dot / (norm_a * norm_b)))
        except ImportError:
            # Pure Python fallback
            dot = sum(x * y for x, y in zip(emb_a, emb_b))
            norm_a = sum(x * x for x in emb_a) ** 0.5
            norm_b = sum(x * x for x in emb_b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 999.0
            return 1.0 - (dot / (norm_a * norm_b))

    # ------------------------------------------------------------------
    # Dynamic Identity Gallery
    # ------------------------------------------------------------------

    def _build_identity_gallery(
        self,
        refs_with_embeddings: List[Dict[str, Any]],
        match_map: Dict[Path, List[Dict[str, Any]]],
        photo_face_embeddings: Dict[Path, List[list]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        """Build per-person gallery from strong, unambiguous direct matches.

        The reference embedding seeds the gallery. A candidate may teach it
        only when its direct score is strong and clearly separated from the
        second identity, preventing self-reinforcing contamination.
        """
        gallery: Dict[str, Dict[str, Any]] = {}
        stats = {"gallery_feeds": 0, "gallery_bootstrap_feeds": 0,
                 "gallery_feeds_blocked": 0,
                 "total_gallery_entries": 0, "rescues_attempted": 0,
                 "references_quarantined": 0,
                 "references_recovered_by_cluster": 0,
                 "recovery_candidates_added": 0}

        reference_paths = {
            ref["path"].resolve(strict=False) for ref in refs_with_embeddings
        }

        for ref in refs_with_embeddings:
            folder = ref["person"]["folder_name"]
            try:
                ref_time = float(ref["path"].stat().st_mtime)
            except OSError:
                ref_time = 0.0
            gallery[folder] = {
                "embeddings": [ref["embedding"]],
                "paths": [ref["path"].resolve(strict=False)],
                "times": [ref_time],
                "person": ref["person"],
                "cluster_members": set(),
                "rejected_cluster_members": set(),
                "secondary_cluster_sizes": {},
                "cluster_size": 0,
                "reference_trusted": bool(ref.get("reference_trusted", True)),
                "reference_recovered": False,
                "reference_path": ref["path"].resolve(strict=False),
                "quarantine_reasons": list(
                    ref.get("reference_quarantine_reasons") or []
                ),
            }
            if not gallery[folder]["reference_trusted"]:
                stats["references_quarantined"] += 1

        recurrent_candidates: Dict[str, List[Dict[str, Any]]] = {}
        recovery_candidates: Dict[str, List[Dict[str, Any]]] = {}
        for image_path, matches in match_map.items():
            # The selected reference already seeds its gallery. Refeeding the
            # whole reference image would reintroduce an accompanying face.
            if image_path.resolve(strict=False) in reference_paths:
                continue
            face_groups: Dict[int, List[Dict[str, Any]]] = {}
            for m in matches:
                face_groups.setdefault(m.get("face_index", 0), []).append(m)
            for face_idx, fm_list in face_groups.items():
                sorted_fm = sorted(fm_list, key=lambda x: float(x.get("distance", 999)))
                face_embs = photo_face_embeddings.get(image_path, [])
                if face_idx >= len(face_embs):
                    continue
                face_emb = face_embs[face_idx]

                # A quarantined reference cannot teach a gallery directly.
                # It may recover only from a coherent multi-photo component
                # that is not already strongly owned by another identity.
                for candidate in sorted_fm:
                    candidate_folder = candidate["person"]["folder_name"]
                    candidate_gallery = gallery.get(candidate_folder)
                    candidate_distance = float(candidate.get("distance", 999))
                    if (
                        not candidate_gallery
                        or candidate_gallery.get("reference_trusted", True)
                        or candidate_distance > self.GALLERY_RECOVERY_MAX_REFERENCE_DISTANCE
                    ):
                        continue
                    competing_distances = [
                        float(other.get("distance", 999))
                        for other in sorted_fm
                        if other["person"]["folder_name"] != candidate_folder
                    ]
                    competitor = min(competing_distances, default=999.0)
                    if (
                        competitor <= self.THRESHOLD_SECURE
                        and candidate_distance - competitor
                        >= self.REFERENCE_CROSS_IDENTITY_MARGIN
                    ):
                        continue
                    try:
                        candidate_time = float(image_path.stat().st_mtime)
                    except OSError:
                        candidate_time = 0.0
                    recovery_candidates.setdefault(candidate_folder, []).append({
                        "embedding": face_emb,
                        "path": image_path.resolve(strict=False),
                        "face_index": face_idx,
                        "distance": candidate_distance,
                        "time": candidate_time,
                        "primary": face_idx == 0,
                    })

                best = sorted_fm[0]
                best_dist = float(best.get("distance", 999))
                # Anti-contamination: top2 too close to top1
                if len(sorted_fm) > 1:
                    second_dist = float(sorted_fm[1].get("distance", 999))
                    identity_margin = second_dist - best_dist
                    if identity_margin <= self.IDENTITY_CONFLICT_MARGIN:
                        stats["gallery_feeds_blocked"] += 1
                        continue
                else:
                    identity_margin = 999.0
                folder = best["person"]["folder_name"]
                if folder not in gallery:
                    continue
                if not gallery[folder].get("reference_trusted", True):
                    stats["gallery_feeds_blocked"] += 1
                    continue
                if (
                    best_dist <= self.GALLERY_BOOTSTRAP_MAX_DISTANCE
                    and identity_margin >= self.GALLERY_BOOTSTRAP_MIN_IDENTITY_MARGIN
                ):
                    try:
                        candidate_time = float(image_path.stat().st_mtime)
                    except OSError:
                        candidate_time = 0.0
                    recurrent_candidates.setdefault(folder, []).append({
                        "embedding": face_emb,
                        "path": image_path.resolve(strict=False),
                        "face_index": face_idx,
                        "distance": best_dist,
                        "time": candidate_time,
                    })
                if best_dist > self.GALLERY_FEED_MAX_DISTANCE:
                    continue
                if len(gallery[folder]["embeddings"]) >= self.GALLERY_MAX_PER_PERSON:
                    stats["gallery_feeds_blocked"] += 1
                    continue
                is_dup = any(
                    self._cosine_distance(face_emb, ex) < self.GALLERY_DUPLICATE_THRESHOLD
                    for ex in gallery[folder]["embeddings"]
                )
                if is_dup:
                    stats["gallery_feeds_blocked"] += 1
                    continue
                gallery[folder]["embeddings"].append(face_emb)
                gallery[folder]["paths"].append(image_path.resolve(strict=False))
                try:
                    gallery[folder]["times"].append(float(image_path.stat().st_mtime))
                except OSError:
                    gallery[folder]["times"].append(0.0)
                stats["gallery_feeds"] += 1

        # Build competing recurrence hypotheses per identity.  Only the
        # dominant component may teach the gallery; a smaller recurrent
        # component is an explicit look-alike/companion hypothesis and is
        # rejected for this identity.
        for folder, candidates in recurrent_candidates.items():
            # Keep only the strongest face hypothesis for a person in a photo.
            best_by_path: Dict[Path, Dict[str, Any]] = {}
            for candidate in candidates:
                previous = best_by_path.get(candidate["path"])
                if previous is None or candidate["distance"] < previous["distance"]:
                    best_by_path[candidate["path"]] = candidate
            candidates = list(best_by_path.values())
            nonzero_times = [item["time"] for item in candidates if item["time"] > 0]
            time_is_informative = (
                len(nonzero_times) >= 2 and max(nonzero_times) - min(nonzero_times) > 1.0
            )

            parents = list(range(len(candidates)))

            def find(index: int) -> int:
                while parents[index] != index:
                    parents[index] = parents[parents[index]]
                    index = parents[index]
                return index

            def union(left: int, right: int) -> None:
                left_root, right_root = find(left), find(right)
                if left_root != right_root:
                    parents[right_root] = left_root

            for left in range(len(candidates)):
                for right in range(left + 1, len(candidates)):
                    visual_distance = self._cosine_distance(
                        candidates[left]["embedding"], candidates[right]["embedding"]
                    )
                    if time_is_informative:
                        time_delta = abs(candidates[left]["time"] - candidates[right]["time"])
                        connected = (
                            time_delta <= self.GALLERY_BOOTSTRAP_MAX_TIME_DELTA
                            or visual_distance <= self.GALLERY_BOOTSTRAP_STRONG_VISUAL_EDGE
                        )
                    else:
                        connected = visual_distance <= self.GALLERY_BOOTSTRAP_PEER_DISTANCE
                    if connected:
                        union(left, right)

            components: Dict[int, List[Dict[str, Any]]] = {}
            for index, candidate in enumerate(candidates):
                components.setdefault(find(index), []).append(candidate)
            ranked_components = sorted(
                components.values(),
                key=lambda component: (
                    -len(component),
                    sum(item["distance"] for item in component) / len(component),
                ),
            )
            dominant: List[Dict[str, Any]] = []
            if ranked_components and len(ranked_components[0]) >= 2:
                second_size = len(ranked_components[1]) if len(ranked_components) > 1 else 0
                if len(ranked_components[0]) > second_size:
                    dominant = ranked_components[0]
            secondary_components = [
                component for component in ranked_components
                if component is not dominant
            ]

            target = gallery[folder]
            dominant_keys = {
                (item["path"], item["face_index"]) for item in dominant
            }
            rejected_keys = {
                (item["path"], item["face_index"])
                for component in secondary_components
                for item in component
            }
            secondary_sizes = {
                (item["path"], item["face_index"]): len(component)
                for component in secondary_components
                for item in component
            }
            target["cluster_members"].update(dominant_keys)
            target["rejected_cluster_members"].update(rejected_keys)
            target["secondary_cluster_sizes"].update(secondary_sizes)
            target["cluster_size"] = len(dominant)

            # Remove any early ultra-strong feed that was later proven to be
            # part of a smaller competing component.
            rejected_paths = {path for path, _face_idx in rejected_keys}
            if rejected_paths:
                retained = [
                    index for index, path in enumerate(target["paths"])
                    if index == 0 or path not in rejected_paths
                ]
                target["embeddings"] = [target["embeddings"][index] for index in retained]
                target["paths"] = [target["paths"][index] for index in retained]
                target["times"] = [target["times"][index] for index in retained]

            for candidate in sorted(dominant, key=lambda item: item["distance"]):
                # Very weak members receive the component label but do not
                # widen the numerical gallery used for other photos.
                if candidate["distance"] > self.THRESHOLD_SECURE:
                    continue
                if len(target["embeddings"]) >= self.GALLERY_MAX_PER_PERSON:
                    stats["gallery_feeds_blocked"] += 1
                    break
                if any(
                    self._cosine_distance(candidate["embedding"], existing)
                    < self.GALLERY_DUPLICATE_THRESHOLD
                    for existing in target["embeddings"]
                ):
                    continue
                target["embeddings"].append(candidate["embedding"])
                target["paths"].append(candidate["path"])
                try:
                    target["times"].append(float(candidate["path"].stat().st_mtime))
                except OSError:
                    target["times"].append(0.0)
                stats["gallery_bootstrap_feeds"] += 1

        # Expand recovery beyond direct reference matches. A damaged/very small
        # anchor may be farther than the normal candidate threshold, while the
        # real person's surrounding photos still form a strong visual component.
        for folder, target in gallery.items():
            if target.get("reference_trusted", True):
                continue
            try:
                reference_time = float(target["reference_path"].stat().st_mtime)
            except OSError:
                reference_time = 0.0
            reference_embedding = target["embeddings"][0]
            for image_path, face_embeddings in photo_face_embeddings.items():
                resolved_path = image_path.resolve(strict=False)
                if resolved_path in reference_paths:
                    continue
                try:
                    candidate_time = float(image_path.stat().st_mtime)
                except OSError:
                    candidate_time = 0.0
                if (
                    reference_time > 0
                    and candidate_time > 0
                    and abs(candidate_time - reference_time)
                    > self.GALLERY_RECOVERY_MAX_TIME_DELTA
                ):
                    continue
                image_matches = match_map.get(image_path, [])
                for face_index, face_embedding in enumerate(face_embeddings):
                    strong_trusted_owner = any(
                        int(match.get("face_index", 0)) == face_index
                        and gallery.get(
                            match["person"]["folder_name"], {}
                        ).get("reference_trusted", True)
                        and float(match.get("distance", 999)) <= self.THRESHOLD_SECURE
                        for match in image_matches
                    )
                    if strong_trusted_owner:
                        continue
                    recovery_candidates.setdefault(folder, []).append({
                        "embedding": face_embedding,
                        "path": resolved_path,
                        "face_index": face_index,
                        "distance": self._cosine_distance(
                            face_embedding, reference_embedding
                        ),
                        "time": candidate_time,
                        "primary": face_index == 0,
                    })

        # Recover a quarantined reference from a coherent, exclusive temporal
        # component. The raw reference remains quarantined and never becomes a
        # voting anchor; the recovered photos become the identity evidence.
        recovery_proposals: Dict[str, List[Dict[str, Any]]] = {}
        for folder, candidates in recovery_candidates.items():
            target = gallery.get(folder)
            if not target or target.get("reference_trusted", True):
                continue
            best_by_face: Dict[Tuple[Path, int], Dict[str, Any]] = {}
            for candidate in candidates:
                key = (candidate["path"], candidate["face_index"])
                previous = best_by_face.get(key)
                if previous is None or candidate["distance"] < previous["distance"]:
                    best_by_face[key] = candidate
            components = self._cluster_embedding_items(
                list(best_by_face.values()),
                max_distance=self.GALLERY_RECOVERY_PEER_DISTANCE,
            )
            eligible = []
            try:
                reference_time = float(target["reference_path"].stat().st_mtime)
            except OSError:
                reference_time = 0.0
            for component in components:
                distinct_paths = {item["path"] for item in component}
                if len(distinct_paths) < self.GALLERY_RECOVERY_MIN_PHOTOS:
                    continue
                nonzero_times = [item["time"] for item in component if item["time"] > 0]
                median_delta = (
                    statistics.median(
                        abs(item_time - reference_time) for item_time in nonzero_times
                    )
                    if reference_time > 0 and nonzero_times else 0.0
                )
                if (
                    reference_time > 0
                    and nonzero_times
                    and median_delta > self.GALLERY_RECOVERY_MAX_TIME_DELTA
                ):
                    continue
                eligible.append((component, median_delta))
            eligible.sort(key=lambda item: (
                -len({candidate["path"] for candidate in item[0]}),
                -sum(bool(candidate.get("primary")) for candidate in item[0]),
                item[1],
                sum(candidate["distance"] for candidate in item[0]) / len(item[0]),
            ))
            if not eligible:
                continue
            winner, _median_delta = eligible[0]
            winner_size = len({item["path"] for item in winner})
            winner_primary = sum(bool(item.get("primary")) for item in winner)
            runner_size = (
                len({item["path"] for item in eligible[1][0]})
                if len(eligible) > 1 else 0
            )
            runner_primary = (
                sum(bool(item.get("primary")) for item in eligible[1][0])
                if len(eligible) > 1 else 0
            )
            if (
                winner_size < runner_size
                or (winner_size == runner_size and winner_primary <= runner_primary)
            ):
                continue

            recovery_proposals[folder] = sorted(
                winner, key=lambda item: item["distance"]
            )

        # If two weak references propose the same faces, the hypotheses are
        # symmetric. Quarantine both instead of assigning by iteration order.
        conflicted_recoveries = set()
        proposal_items = list(recovery_proposals.items())
        for left_index, (left_folder, left_items) in enumerate(proposal_items):
            left_keys = {(item["path"], item["face_index"]) for item in left_items}
            for right_folder, right_items in proposal_items[left_index + 1:]:
                right_keys = {
                    (item["path"], item["face_index"]) for item in right_items
                }
                if len(left_keys & right_keys) >= self.GALLERY_RECOVERY_MIN_PHOTOS:
                    conflicted_recoveries.update({left_folder, right_folder})

        for folder, winner in recovery_proposals.items():
            if folder in conflicted_recoveries:
                continue
            target = gallery[folder]
            winner_size = len({item["path"] for item in winner})
            target["embeddings"] = [item["embedding"] for item in winner]
            target["paths"] = [item["path"] for item in winner]
            target["times"] = [item["time"] for item in winner]
            target["cluster_members"] = {
                (item["path"], item["face_index"]) for item in winner
            }
            target["cluster_size"] = winner_size
            target["reference_recovered"] = True
            stats["references_recovered_by_cluster"] += 1
            stats["recovery_candidates_added"] += winner_size

        # A recovered gallery gets a second, purely visual candidate pass. This
        # only adds candidates; final ownership is still decided globally.
        for folder, target in gallery.items():
            if not target.get("reference_recovered"):
                continue
            for image_path, face_embeddings in photo_face_embeddings.items():
                if image_path.resolve(strict=False) == target["reference_path"]:
                    continue
                for face_index, face_embedding in enumerate(face_embeddings):
                    distance = min(
                        self._cosine_distance(face_embedding, anchor)
                        for anchor in target["embeddings"]
                    )
                    if distance > self.THRESHOLD_REVIEW:
                        continue
                    existing = [
                        match for match in match_map.get(image_path, [])
                        if match["person"]["folder_name"] == folder
                        and int(match.get("face_index", 0)) == face_index
                    ]
                    if existing and min(
                        float(match.get("distance", 999)) for match in existing
                    ) <= distance:
                        continue
                    match_map.setdefault(image_path, []).append({
                        "person": target["person"],
                        "distance": distance,
                        "verified": distance <= self.THRESHOLD_SECURE,
                        "face_index": face_index,
                        "match_type": (
                            "secure" if distance <= self.THRESHOLD_SECURE else "review"
                        ),
                        "match_source": "recovered_identity_cluster",
                    })

        # Freeze the pure evidence used when a competing component asks to
        # rejoin. Iterative rescues may grow the live gallery, but can never
        # manufacture votes for another secondary component.
        for target in gallery.values():
            target["anchor_embeddings"] = list(target["embeddings"])
            target["anchor_paths"] = list(target["paths"])
            target["anchor_times"] = list(target["times"])

        stats["total_gallery_entries"] = sum(len(g["embeddings"]) for g in gallery.values())
        return gallery, stats

    def _try_gallery_rescue(
        self,
        face_embedding: list,
        gallery_embeddings: List[list],
        *,
        candidate_path: Optional[Path] = None,
        gallery_paths: Optional[List[Path]] = None,
        gallery_times: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Score a face against a recurrent identity gallery.

        Time is a small positive prior, never a veto.  Acceptance is based on
        several distinct visual examples, a robust spherical centroid and an
        adaptive radius learned from the identity's own variation.
        """
        candidate_resolved = (
            candidate_path.resolve(strict=False) if candidate_path else None
        )
        pairs = []
        for index, embedding in enumerate(gallery_embeddings or []):
            gallery_path = (
                gallery_paths[index]
                if gallery_paths is not None and index < len(gallery_paths)
                else None
            )
            if (
                candidate_resolved is not None
                and gallery_path is not None
                and Path(gallery_path).resolve(strict=False) == candidate_resolved
            ):
                continue
            gallery_time = (
                float(gallery_times[index])
                if gallery_times is not None and index < len(gallery_times)
                else 0.0
            )
            pairs.append((self._cosine_distance(face_embedding, embedding), gallery_time))

        if len(pairs) < 2:
            return {"rescued": False, "best_gallery_distance": 999.0,
                    "avg_top3": 999.0, "supporter_avg": 999.0,
                    "supporter_count": 0, "temporal_support": False,
                    "centroid_distance": 999.0, "robust_score": 999.0,
                    "adaptive_radius": self.GALLERY_ADAPTIVE_RADIUS_MIN}
        pairs.sort(key=lambda item: item[0])
        distances = [item[0] for item in pairs]
        best = distances[0]
        top3 = distances[:min(3, len(distances))]
        avg_top3 = sum(top3) / len(top3)

        # Learn how much this identity changes across pose, crop and light.
        # A pure but visually varied gallery receives a wider radius; a tight
        # gallery keeps a conservative one.
        internal_distances = []
        usable_embeddings = []
        for index, embedding in enumerate(gallery_embeddings or []):
            gallery_path = (
                gallery_paths[index]
                if gallery_paths is not None and index < len(gallery_paths)
                else None
            )
            if (
                candidate_resolved is not None and gallery_path is not None
                and Path(gallery_path).resolve(strict=False) == candidate_resolved
            ):
                continue
            usable_embeddings.append(embedding)
        for index, embedding in enumerate(usable_embeddings):
            for other in usable_embeddings[index + 1:]:
                internal_distances.append(self._cosine_distance(embedding, other))
        if internal_distances:
            internal_median = statistics.median(internal_distances)
            adaptive_radius = min(
                self.GALLERY_ADAPTIVE_RADIUS_MAX,
                max(self.GALLERY_ADAPTIVE_RADIUS_MIN, internal_median + 0.12),
            )
        else:
            adaptive_radius = self.GALLERY_ADAPTIVE_RADIUS_MIN

        centroid_distance = 999.0
        if usable_embeddings:
            dimensions = min(len(embedding) for embedding in usable_embeddings)
            normalized = []
            for embedding in usable_embeddings:
                norm = math.sqrt(sum(float(value) ** 2 for value in embedding[:dimensions]))
                if norm > 0:
                    normalized.append([float(value) / norm for value in embedding[:dimensions]])
            if normalized:
                centroid = [
                    sum(row[index] for row in normalized) / len(normalized)
                    for index in range(dimensions)
                ]
                centroid_distance = self._cosine_distance(
                    list(face_embedding)[:dimensions], centroid,
                )

        supporter_pairs = [
            item for item in pairs if item[0] <= adaptive_radius
        ]
        supporter_distances = [item[0] for item in supporter_pairs]
        supporters = len(supporter_distances)
        supporter_avg = (
            sum(supporter_distances) / supporters if supporters else 999.0
        )
        candidate_time = 0.0
        if candidate_path is not None:
            try:
                candidate_time = float(candidate_path.stat().st_mtime)
            except OSError:
                candidate_time = 0.0
        nonzero_gallery_times = [time_value for _distance, time_value in pairs if time_value > 0]
        time_is_informative = (
            candidate_time > 0
            and len(nonzero_gallery_times) >= 2
            and max(nonzero_gallery_times) - min(nonzero_gallery_times) > 1.0
        )
        temporal_support = False
        if time_is_informative:
            temporal_support = any(
                gallery_time > 0
                and abs(candidate_time - gallery_time)
                <= self.GALLERY_TWO_VOTE_MAX_TIME_DELTA
                for _distance, gallery_time in supporter_pairs
            )
        median_top3 = statistics.median(top3)
        robust_score = (
            0.50 * median_top3
            + 0.30 * centroid_distance
            + 0.20 * best
        )
        if temporal_support:
            robust_score = max(0.0, robust_score - 0.02)

        three_vote_visual = (
            supporters >= self.GALLERY_STRONG_SUPPORTERS
            and robust_score <= min(0.76, adaptive_radius)
        )
        two_vote_visual = (
            supporters >= self.GALLERY_RESCUE_MIN_SUPPORTERS
            and robust_score <= self.GALLERY_RESCUE_MAX_AVG
        )
        # At least one independent gallery anchor must pass the original hard
        # visual bound. A wide adaptive cloud alone cannot rescue a stranger.
        rescued = (
            best <= self.GALLERY_RESCUE_MAX_DISTANCE
            and (three_vote_visual or two_vote_visual)
        )
        return {"rescued": rescued, "best_gallery_distance": best,
                "avg_top3": avg_top3, "supporter_avg": supporter_avg,
                "supporter_count": supporters,
                "temporal_support": temporal_support,
                "centroid_distance": centroid_distance,
                "robust_score": robust_score,
                "adaptive_radius": adaptive_radius}

    def _resolve_assignments(
        self,
        match_map: Dict[Path, List[Dict[str, Any]]],
        *,
        ambiguity_margin: float,
        gallery_data: Optional[Dict[str, Dict[str, Any]]] = None,
        photo_face_embeddings: Optional[Dict[Path, List[list]]] = None,
    ) -> Tuple[Dict[Path, List[Dict[str, Any]]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Premium assignment resolver with three-tier decision making + gallery rescue.

        Returns:
            confirmed:  {image_path -> [list of persons]} — secure matches
            review:     [{image_path, matches, reason}] — dubious -> Pendientes
            conflicts:  [{image_path, candidates}] — identity conflicts
            rescue_details: [{}] — gallery rescue info for reporting
        """
        confirmed: Dict[Path, List[Dict[str, Any]]] = {}
        review: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        rescue_details: List[Dict[str, Any]] = []

        def choose_gallery_option(
            image_path: Path,
            face_idx: int,
            candidates: List[Dict[str, Any]],
        ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
            if not gallery_data or not photo_face_embeddings:
                return None
            face_embs = photo_face_embeddings.get(image_path, [])
            if face_idx >= len(face_embs):
                return None
            face_embedding = face_embs[face_idx]
            options = []
            for candidate in candidates:
                if float(candidate.get("distance", 999)) > self.THRESHOLD_REVIEW:
                    continue
                folder = candidate["person"]["folder_name"]
                gal = gallery_data.get(folder)
                if not gal:
                    continue
                candidate_key = (image_path.resolve(strict=False), face_idx)
                is_secondary_cluster = (
                    candidate_key in gal.get("rejected_cluster_members", set())
                )
                scoring_embeddings = (
                    gal.get("anchor_embeddings", gal["embeddings"])
                    if is_secondary_cluster else gal["embeddings"]
                )
                scoring_paths = (
                    gal.get("anchor_paths", gal.get("paths"))
                    if is_secondary_cluster else gal.get("paths")
                )
                scoring_times = (
                    gal.get("anchor_times", gal.get("times"))
                    if is_secondary_cluster else gal.get("times")
                )
                result = self._try_gallery_rescue(
                    face_embedding,
                    scoring_embeddings,
                    candidate_path=image_path,
                    gallery_paths=scoring_paths,
                    gallery_times=scoring_times,
                )
                # A secondary session is not automatically a different person.
                # It may rejoin only through strong evidence from at least three
                # photos of the dominant gallery.  Its own component was removed
                # above, so it cannot vote for itself.
                # Four independent anchor photos proved sufficient to recover
                # a real second session in validation, while the competing
                # look-alike components reached only two.  Keep this fixed and
                # conservative; live/secondary photos never count here.
                required_secondary_support = 4
                if is_secondary_cluster and not (
                    result.get("rescued")
                    and int(result.get("supporter_count", 0))
                    >= required_secondary_support
                    and float(result.get("robust_score", 999))
                    <= self.GALLERY_RESCUE_MAX_AVG
                ):
                    continue
                if candidate_key in gal.get("cluster_members", set()):
                    result["rescued"] = True
                    result["cluster_consensus"] = True
                    result["supporter_count"] = max(
                        int(result.get("supporter_count", 0)),
                        max(2, int(gal.get("cluster_size", 0)) - 1),
                    )
                    result["robust_score"] = min(
                        float(result.get("robust_score", 999)), 0.58,
                    )
                result["identity_score"] = (
                    0.75 * float(result.get("robust_score", result.get("supporter_avg", 999)))
                    + 0.25 * float(candidate.get("distance", 999))
                )
                options.append((candidate, result))
            options.sort(key=lambda item: (
                item[1]["identity_score"],
                -item[1]["supporter_count"],
                item[1]["best_gallery_distance"],
                float(item[0].get("distance", 999)),
            ))
            if not options or not options[0][1]["rescued"]:
                return None
            if len(options) > 1:
                first_result = options[0][1]
                second_result = options[1][1]
                clear_consensus = (
                    not second_result["rescued"]
                    or second_result["identity_score"] - first_result["identity_score"]
                    >= self.IDENTITY_GALLERY_MARGIN
                    or first_result["supporter_count"] >= second_result["supporter_count"] + 2
                )
                if not clear_consensus:
                    return None
            return options[0]

        def append_gallery_evidence(
            folder: str,
            image_path: Path,
            face_embedding: list,
            rescue_result: Optional[Dict[str, Any]] = None,
        ) -> None:
            if not gallery_data or folder not in gallery_data:
                return
            if rescue_result is not None and (
                float(rescue_result.get("best_gallery_distance", 999))
                > self.GALLERY_RESCUE_FEED_MAX_DISTANCE
                or float(rescue_result.get("robust_score", 999))
                > self.GALLERY_RESCUE_FEED_MAX_ROBUST_SCORE
            ):
                return
            gallery_embeddings = gallery_data[folder]["embeddings"]
            if len(gallery_embeddings) >= self.GALLERY_MAX_PER_PERSON:
                return
            if any(
                self._cosine_distance(face_embedding, existing)
                < self.GALLERY_DUPLICATE_THRESHOLD
                for existing in gallery_embeddings
            ):
                return
            gallery_embeddings.append(face_embedding)
            gallery_data[folder].setdefault("paths", []).append(
                image_path.resolve(strict=False)
            )
            try:
                gallery_time = float(image_path.stat().st_mtime)
            except OSError:
                gallery_time = 0.0
            gallery_data[folder].setdefault("times", []).append(gallery_time)

        for image_path, matches in match_map.items():
            # Group best match per (person, face_index) pair
            # Key: (folder_name, face_index)
            best_per_face_person: Dict[Tuple[str, int], Dict[str, Any]] = {}
            for match in matches:
                person = match["person"]
                face_idx = match.get("face_index", 0)
                key = (person["folder_name"], face_idx)
                prev = best_per_face_person.get(key)
                if prev is None or float(match.get("distance", 999)) < float(prev.get("distance", 999)):
                    best_per_face_person[key] = match

            # Group by face_index to detect conflicts (same face matching multiple people)
            faces: Dict[int, List[Dict[str, Any]]] = {}
            for (folder_name, face_idx), match in best_per_face_person.items():
                faces.setdefault(face_idx, []).append(match)

            secure_persons: Dict[str, Dict[str, Any]] = {}  # folder_name -> person
            image_has_conflict = False
            image_review_matches: List[Dict[str, Any]] = []

            for face_idx, face_matches in faces.items():
                sorted_fm = sorted(face_matches, key=lambda m: float(m.get("distance", 999)))
                best = sorted_fm[0]
                best_dist = float(best.get("distance", 999))
                match_type = best.get("match_type", "review")
                best_folder = best["person"]["folder_name"]
                best_gallery = (gallery_data or {}).get(best_folder, {})
                best_is_rejected_cluster = (
                    (image_path.resolve(strict=False), face_idx)
                    in best_gallery.get("rejected_cluster_members", set())
                )
                is_reference_photo = (
                    image_path.resolve(strict=False)
                    == best_gallery.get("reference_path")
                )
                direct_identity_allowed = (
                    best_gallery.get("reference_trusted", True)
                    or is_reference_photo
                )

                # Identity conflict detection: same face, two close matches
                if len(sorted_fm) > 1:
                    second = sorted_fm[1]
                    second_dist = float(second.get("distance", 999))
                    if second_dist - best_dist <= self.IDENTITY_CONFLICT_MARGIN and best_dist <= self.THRESHOLD_REVIEW:
                        consensus = choose_gallery_option(
                            image_path, face_idx, sorted_fm,
                        )
                        if consensus is not None:
                            rescued_match, rescue_result = consensus
                            folder = rescued_match["person"]["folder_name"]
                            rescued_dist = float(rescued_match.get("distance", 999))
                            person_copy = dict(rescued_match["person"])
                            person_copy["_best_dist"] = rescued_dist
                            secure_persons[folder] = person_copy
                            rescue_details.append({
                                "image_path": image_path,
                                "person_display_name": rescued_match["person"]["display_name"],
                                "distance_base": rescued_dist,
                                "distance_gallery": rescue_result["best_gallery_distance"],
                                "supporter_count": rescue_result["supporter_count"],
                                "supporter_avg": rescue_result["supporter_avg"],
                                "temporal_support": rescue_result.get("temporal_support", False),
                                "avg_top3": rescue_result["avg_top3"],
                            })
                            face_embs = (photo_face_embeddings or {}).get(image_path, [])
                            if face_idx < len(face_embs):
                                append_gallery_evidence(
                                    folder, image_path, face_embs[face_idx], rescue_result,
                                )
                            continue
                        conflicts.append({
                            "image_path": image_path,
                            "face_index": face_idx,
                            "candidates": sorted_fm[:2],
                        })
                        image_has_conflict = True
                        continue  # Don't assign this face to anyone

                if (
                    best_dist <= self.DIRECT_CORE_THRESHOLD
                    and not best_is_rejected_cluster
                    and direct_identity_allowed
                ):
                    folder = best["person"]["folder_name"]
                    if folder not in secure_persons or best_dist < float(secure_persons[folder].get("_best_dist", 999)):
                        person_copy = dict(best["person"])
                        person_copy["_best_dist"] = best_dist
                        secure_persons[folder] = person_copy
                elif best_dist <= self.THRESHOLD_REVIEW:
                    # --- Consensus rescue across every plausible identity ---
                    # The nearest reference is not always the correct identity
                    # for a hard face. Evaluate every candidate against its
                    # independently built gallery and require multiple votes.
                    face_embs = (photo_face_embeddings or {}).get(image_path, [])
                    rescued_option = choose_gallery_option(
                        image_path, face_idx, sorted_fm,
                    )

                    if rescued_option is not None:
                        rescued_match, rescue_result = rescued_option
                        folder = rescued_match["person"]["folder_name"]
                        rescued_dist = float(rescued_match.get("distance", 999))
                        if folder not in secure_persons or rescued_dist < float(secure_persons[folder].get("_best_dist", 999)):
                            person_copy = dict(rescued_match["person"])
                            person_copy["_best_dist"] = rescued_dist
                            secure_persons[folder] = person_copy
                        rescue_details.append({
                            "image_path": image_path,
                            "person_display_name": rescued_match["person"]["display_name"],
                            "distance_base": rescued_dist,
                            "distance_gallery": rescue_result["best_gallery_distance"],
                            "supporter_count": rescue_result["supporter_count"],
                            "supporter_avg": rescue_result["supporter_avg"],
                            "temporal_support": rescue_result.get("temporal_support", False),
                            "avg_top3": rescue_result["avg_top3"],
                        })

                        # Iterative evidence: a consensus-rescued face may help
                        # later hard samples, but only if it is not a duplicate.
                        face_embedding = face_embs[face_idx]
                        append_gallery_evidence(
                            folder, image_path, face_embedding, rescue_result,
                        )
                    else:
                        image_review_matches.append(best)

            # Build confirmed list (multi-person per image is valid)
            if secure_persons:
                person_list = []
                for p in secure_persons.values():
                    p.pop("_best_dist", None)
                    person_list.append(p)
                confirmed[image_path] = person_list

            # Review items (dubious zone or leftover non-secure matches)
            if image_review_matches and not image_has_conflict:
                review.append({
                    "image_path": image_path,
                    "matches": image_review_matches,
                    "reason": "zona_dudosa",
                })

        # ------------------------------------------------------------------
        # Second pass: consensus recovery of border-reference faces.
        # A student whose reference sits near the 0.40 limit (e.g. a different
        # expression/angle than the event) can miss some group photos even when
        # his face is nearly identical to the ones already accepted. The
        # reference is too far, but his own already-confirmed event faces are
        # not. Anchor on those confirmed faces (NOT the strict <=0.22 gallery,
        # which such a student never fed), require >=2 supporters within
        # THRESHOLD_SECURE and a clear margin over every other identity, so a
        # stranger or look-alike can never be pulled in. Precision-preserving.
        # ------------------------------------------------------------------
        if (
            photo_face_embeddings and gallery_data
            and not os.environ.get("FACESYNC_NO_CONSENSUS_RESCUE")
        ):
            confirmed_anchors: Dict[str, List[list]] = {}
            assigned_face_keys: set = set()
            for img, person_list in confirmed.items():
                folders = {p["folder_name"] for p in person_list}
                embs = photo_face_embeddings.get(img, [])
                for m in match_map.get(img, []):
                    fol = m["person"]["folder_name"]
                    fi = int(m.get("face_index", 0))
                    if (
                        fol in folders
                        and float(m.get("distance", 999)) <= self.THRESHOLD_REVIEW
                        and 0 <= fi < len(embs)
                    ):
                        confirmed_anchors.setdefault(fol, []).append(embs[fi])
                        assigned_face_keys.add((img.resolve(strict=False), fi))
            conflicted_face_keys = {
                (c["image_path"].resolve(strict=False), int(c.get("face_index", 0)))
                for c in conflicts
            }
            min_anchors = self.GALLERY_RESCUE_MIN_SUPPORTERS
            for img, face_embs in photo_face_embeddings.items():
                for fi, face_emb in enumerate(face_embs):
                    key = (img.resolve(strict=False), fi)
                    if key in assigned_face_keys or key in conflicted_face_keys:
                        continue
                    scored = []
                    for fol, anchors in confirmed_anchors.items():
                        dists = [self._cosine_distance(face_emb, a) for a in anchors]
                        if not dists:
                            continue
                        sup = sum(1 for d in dists if d <= self.THRESHOLD_SECURE)
                        scored.append((sup, min(dists), fol))
                    if not scored:
                        continue
                    scored.sort(key=lambda x: (-x[0], x[1]))
                    sup, best, fol = scored[0]
                    if sup < min_anchors or best > self.THRESHOLD_SECURE:
                        continue
                    if len(scored) > 1:
                        sup2, best2, _f2 = scored[1]
                        if sup2 >= min_anchors and (best2 - best) < self.IDENTITY_GALLERY_MARGIN:
                            continue  # two identities claim this face -> too risky
                    person = (gallery_data.get(fol) or {}).get("person")
                    if not person:
                        continue
                    bucket = confirmed.setdefault(img, [])
                    if any(p["folder_name"] == fol for p in bucket):
                        assigned_face_keys.add(key)
                        continue
                    bucket.append(dict(person))
                    assigned_face_keys.add(key)
                    rescue_details.append({
                        "image_path": img,
                        "person_display_name": person["display_name"],
                        "distance_base": best,
                        "distance_gallery": best,
                        "supporter_count": sup,
                        "supporter_avg": best,
                        "temporal_support": False,
                        "avg_top3": best,
                        "motivo": "consenso_rostros_confirmados",
                    })

        return confirmed, review, conflicts, rescue_details

    @staticmethod
    def _last_number(value: Any) -> Optional[int]:
        nums = re.findall(r"\d+", str(value or ""))
        if not nums:
            return None
        try:
            return int(nums[-1])
        except ValueError:
            return None

    def _audit_reference_collisions(
        self,
        people: List[Dict[str, Any]],
        refs_with_embeddings: List[Dict[str, Any]],
        photo_face_embeddings: Dict[Path, List[list]],
        match_map: Dict[Path, List[Dict[str, Any]]],
        report: Dict[str, Any],
    ) -> None:
        """Repair crossed strong references before gallery construction.

        A filename can be changed to another student's number while still
        producing a coherent (but wrong) reference gallery. This audit compares
        each reference with coherent face clusters in its numeric neighborhood
        and with the other reference neighborhoods. When a reference is clearly
        closer to another student's cluster, the corrected cluster becomes the
        post-motor anchor and its old match entries are recalculated.

        This is an evidence/delivery layer: ArcFace, RetinaFace, thresholds,
        and the recognition implementation remain untouched.
        """
        if not refs_with_embeddings or not photo_face_embeddings:
            return

        reference_paths = {
            ref.get("path").resolve(strict=False)
            for ref in refs_with_embeddings
            if ref.get("path")
        }
        items: List[Dict[str, Any]] = []
        for path, embeddings in photo_face_embeddings.items():
            resolved = path.resolve(strict=False)
            if resolved in reference_paths:
                continue
            number = self._last_number(path.stem)
            if number is None:
                continue
            for face_index, embedding in enumerate(embeddings or []):
                if embedding:
                    items.append({
                        "path": resolved,
                        "embedding": embedding,
                        "number": number,
                        "face_index": face_index,
                        "stem": path.stem.lower(),
                    })
        if not items:
            return

        def collapse_component(component: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            by_stem: Dict[str, List[Dict[str, Any]]] = {}
            for item in component:
                by_stem.setdefault(item["stem"], []).append(item)
            if len(by_stem) < self.REFERENCE_COLLISION_MIN_STEMS:
                return None
            representatives: List[Dict[str, Any]] = []
            for stem_items in by_stem.values():
                first = stem_items[0]
                representatives.append(min(
                    stem_items,
                    key=lambda item: self._cosine_distance(
                        item["embedding"], first["embedding"]
                    ),
                ))
            pair_distances = []
            for left in range(len(representatives)):
                for right in range(left + 1, len(representatives)):
                    pair_distances.append(self._cosine_distance(
                        representatives[left]["embedding"],
                        representatives[right]["embedding"],
                    ))
            medoid = min(
                representatives,
                key=lambda item: sum(
                    self._cosine_distance(item["embedding"], other["embedding"])
                    for other in representatives
                ),
            )
            numbers = sorted({int(item["number"]) for item in representatives})
            return {
                "items": representatives,
                "embeddings": [item["embedding"] for item in representatives],
                "paths": [item["path"] for item in representatives],
                "numbers": numbers,
                "stems": sorted(by_stem),
                "size": len(representatives),
                "medoid": medoid["embedding"],
                "coherence": round(
                    sum(pair_distances) / max(1, len(pair_distances)), 4
                ),
            }

        profiles: Dict[str, Dict[str, Any]] = {}
        for ref in refs_with_embeddings:
            person = ref.get("person") or {}
            folder = str(person.get("folder_name", ""))
            reference_number = self._last_number(
                person.get("reference_value")
                or (Path(ref.get("path")).stem if ref.get("path") else "")
            )
            if reference_number is None or not ref.get("embedding"):
                continue
            nearby = [
                item for item in items
                if abs(int(item["number"]) - reference_number)
                <= self.REFERENCE_COLLISION_WINDOW
            ]
            components = self._cluster_embedding_items(
                nearby, max_distance=self.REFERENCE_COLLISION_CLUSTER_DISTANCE
            )
            clusters = []
            for component in components:
                cluster = collapse_component(component)
                if not cluster:
                    continue
                cluster["numeric_gap"] = min(
                    abs(number - reference_number) for number in cluster["numbers"]
                )
                cluster["contains_reference"] = reference_number in set(cluster["numbers"])
                cluster["reference_distance"] = min(
                    self._cosine_distance(ref["embedding"], embedding)
                    for embedding in cluster["embeddings"]
                )
                clusters.append(cluster)
            clusters.sort(key=lambda cluster: (
                -int(cluster["size"]),
                0 if cluster["contains_reference"] else 1,
                int(cluster["numeric_gap"]),
                float(cluster["reference_distance"]),
                tuple(cluster["stems"]),
            ))
            profiles[folder] = {
                "ref": ref,
                "number": reference_number,
                "clusters": clusters,
                "evidence_clusters": [],
            }

        # Build an independent evidence view from the motor's provisional
        # matches.  This is deliberately separate from the numeric windows:
        # a crossed reference may be far from the real owner's number (for
        # example, a 2462 file containing the face from the 2405 session).
        # Only unique, secure faces with a clear identity margin may teach this
        # view; a conflict cannot certify itself.
        evidence_items_by_folder: Dict[str, List[Dict[str, Any]]] = {}
        for image_path, embeddings in photo_face_embeddings.items():
            resolved_image = image_path.resolve(strict=False)
            if resolved_image in reference_paths:
                continue
            matches_for_image = match_map.get(image_path)
            if matches_for_image is None:
                matches_for_image = match_map.get(resolved_image, [])
            for face_index, embedding in enumerate(embeddings or []):
                face_matches = [
                    match for match in (matches_for_image or [])
                    if int(match.get("face_index", 0) or 0) == face_index
                ]
                ranked = sorted(
                    face_matches,
                    key=lambda match: float(match.get("distance", 999)),
                )
                if not ranked:
                    continue
                best_distance = float(ranked[0].get("distance", 999))
                second_distance = float(
                    ranked[1].get("distance", 999)
                ) if len(ranked) > 1 else 999.0
                if best_distance > self.THRESHOLD_SECURE:
                    continue
                if (
                    len(ranked) > 1
                    and second_distance - best_distance
                    <= self.IDENTITY_CONFLICT_MARGIN
                ):
                    continue
                number = self._last_number(image_path.stem)
                if number is None or not embedding:
                    continue
                best_person = ranked[0].get("person") or {}
                best_folder = str(best_person.get("folder_name", ""))
                if not best_folder:
                    continue
                evidence_items_by_folder.setdefault(best_folder, []).append({
                    "path": resolved_image,
                    "embedding": embedding,
                    "number": number,
                    "face_index": face_index,
                    "stem": image_path.stem.lower(),
                })

        for folder, evidence_items in evidence_items_by_folder.items():
            profile = profiles.get(folder)
            if not profile:
                continue
            evidence_components = self._cluster_embedding_items(
                evidence_items,
                max_distance=self.REFERENCE_COLLISION_CLUSTER_DISTANCE,
            )
            evidence_clusters = []
            for component in evidence_components:
                cluster = collapse_component(component)
                if not cluster:
                    continue
                if int(cluster["size"]) < self.REFERENCE_COLLISION_GLOBAL_MIN_STEMS:
                    continue
                cluster["source"] = "asignaciones_seguras_postmotor"
                evidence_clusters.append(cluster)
            evidence_clusters.sort(key=lambda cluster: (
                -int(cluster["size"]),
                float(cluster["coherence"]),
                tuple(cluster["stems"]),
            ))
            profile["evidence_clusters"] = evidence_clusters

        audits = report.setdefault("auditoria_referencias_cruzadas", [])
        repaired_folders: set[str] = set()
        for target_folder, target_profile in profiles.items():
            if target_folder in repaired_folders:
                continue
            target_ref = target_profile["ref"]
            target_embedding = target_ref.get("embedding")
            target_clusters = target_profile.get("clusters") or []
            target_evidence_clusters = target_profile.get("evidence_clusters") or []
            target_all_clusters = list(target_clusters) + list(target_evidence_clusters)
            if not target_embedding or not target_all_clusters:
                continue

            candidates = []
            for owner_folder, owner_profile in profiles.items():
                if owner_folder == target_folder:
                    continue
                owner_ref = owner_profile["ref"]
                owner_embedding = owner_ref.get("embedding")
                if not owner_embedding:
                    continue
                ref_distance = self._cosine_distance(target_embedding, owner_embedding)
                owner_clusters = []
                for cluster in (owner_profile.get("clusters") or []):
                    cluster = dict(cluster)
                    cluster["source"] = "ventana_numerica"
                    owner_clusters.append(cluster)
                owner_clusters.extend(owner_profile.get("evidence_clusters") or [])
                if not owner_clusters:
                    continue
                for owner_cluster in owner_clusters:
                    if (
                        owner_cluster.get("source") == "asignaciones_seguras_postmotor"
                        and int(owner_cluster.get("size", 0))
                        < self.REFERENCE_COLLISION_GLOBAL_MIN_STEMS
                    ):
                        continue
                    target_to_owner_group = min(
                        self._cosine_distance(target_embedding, embedding)
                        for embedding in owner_cluster["embeddings"]
                    )
                    if owner_cluster.get("source") == "asignaciones_seguras_postmotor":
                        if target_to_owner_group > self.REFERENCE_COLLISION_GLOBAL_MAX_DISTANCE:
                            continue
                    elif ref_distance > self.THRESHOLD_SECURE:
                        continue
                    own_distance = min(
                        self._cosine_distance(target_embedding, embedding)
                        for cluster in target_all_clusters
                        for embedding in cluster["embeddings"]
                    )
                    if own_distance <= target_to_owner_group:
                        continue
                    margin = (
                        self.REFERENCE_COLLISION_GLOBAL_MARGIN
                        if owner_cluster.get("source") == "asignaciones_seguras_postmotor"
                        else self.REFERENCE_COLLISION_MIN_MARGIN
                    )
                    if target_to_owner_group + margin > own_distance:
                        continue
                    candidates.append({
                        "owner_folder": owner_folder,
                        "owner_ref": owner_ref,
                        "owner_cluster": owner_cluster,
                        "reference_distance": ref_distance,
                        "target_to_owner_group": target_to_owner_group,
                        "own_distance": own_distance,
                    })
            if not candidates:
                continue

            collision = min(candidates, key=lambda candidate: (
                float(candidate["target_to_owner_group"]),
                -int(candidate["owner_cluster"]["size"]),
                str(candidate["owner_folder"]).lower(),
            ))
            owner_ref = collision["owner_ref"]

            safe_clusters = [
                cluster for cluster in target_all_clusters
                if min(
                    self._cosine_distance(cluster_embedding, owner_ref.get("embedding"))
                    for cluster_embedding in cluster["embeddings"]
                ) > self.THRESHOLD_SECURE
            ]
            if not safe_clusters:
                continue
            repair_cluster = min(safe_clusters, key=lambda cluster: (
                -int(cluster["size"]),
                0 if cluster.get("contains_reference", False) else 1,
                int(cluster.get("numeric_gap", 999999)),
                float(cluster["coherence"]),
                tuple(cluster["stems"]),
            ))
            repair_embeddings = list(repair_cluster["embeddings"])
            repair_embedding = repair_cluster["medoid"]

            original_path = target_ref.get("path")
            target_ref["embedding"] = repair_embedding
            target_ref["embeddings"] = [repair_embedding]
            target_ref["candidate_faces"] = [{
                "embedding": repair_embedding,
                "face_confidence": 1.0,
            }]
            target_ref["reference_trusted"] = True
            target_ref["reference_recovered"] = True
            target_ref["reference_collision_repaired"] = True
            target_ref["reference_source"] = "postmotor_numeric_cluster"

            target_person = target_ref.get("person") or {}
            owner_person = owner_ref.get("person") or {}
            target_name = str(target_person.get("display_name", target_folder))
            owner_name = str(owner_person.get("display_name", collision["owner_folder"]))

            # Re-evaluate every extracted face, not only files that already had
            # a provisional match.  A crossed reference can make the real
            # owner's photos fall outside the old target entry; adding the
            # repaired candidate here lets the unchanged global resolver make
            # the final assignment before delivery.
            for image_path, face_embeddings in list(photo_face_embeddings.items()):
                resolved_image = image_path.resolve(strict=False)
                existing_key = image_path
                if existing_key not in match_map:
                    existing_key = next(
                        (
                            key for key in match_map
                            if key.resolve(strict=False) == resolved_image
                        ),
                        image_path,
                    )
                updated_matches = []
                target_face_indices: set[int] = set()
                owner_face_indices: set[int] = set()
                for match in list(match_map.get(existing_key, [])):
                    if match.get("person", {}).get("folder_name") == collision["owner_folder"]:
                        owner_face_indices.add(int(match.get("face_index", 0) or 0))
                    if match.get("person", {}).get("folder_name") != target_folder:
                        updated_matches.append(match)
                        continue
                    if original_path and resolved_image == original_path.resolve(strict=False):
                        continue
                    face_index = int(match.get("face_index", 0) or 0)
                    if face_index < 0 or face_index >= len(face_embeddings):
                        continue
                    distance = min(
                        self._cosine_distance(face_embeddings[face_index], anchor)
                        for anchor in repair_embeddings
                    )
                    if distance > self.THRESHOLD_REVIEW:
                        continue
                    repaired_match = dict(match)
                    repaired_match["distance"] = distance
                    repaired_match["verified"] = distance <= self.THRESHOLD_SECURE
                    repaired_match["match_source"] = "postmotor_reference_collision_repair"
                    updated_matches.append(repaired_match)
                    target_face_indices.add(face_index)

                for face_index, face_embedding in enumerate(face_embeddings or []):
                    distance = min(
                        self._cosine_distance(face_embedding, anchor)
                        for anchor in repair_embeddings
                    )
                    if distance <= self.THRESHOLD_REVIEW and face_index not in target_face_indices:
                        updated_matches.append({
                            "person": target_person,
                            "distance": distance,
                            "verified": distance <= self.THRESHOLD_SECURE,
                            "face_index": face_index,
                            "match_type": (
                                "secure" if distance <= self.THRESHOLD_SECURE else "review"
                            ),
                            "match_source": "postmotor_reference_collision_repair",
                        })
                        target_face_indices.add(face_index)

                # The original wrong reference was force-matched to the target
                # by the motor.  Give the competing owner an evidence-based
                # candidate so the final resolver can remove it from the wrong
                # folder instead of preserving the forced reference assignment.
                if original_path and resolved_image == original_path.resolve(strict=False):
                    owner_embedding = owner_ref.get("embedding")
                    if owner_embedding:
                        for face_index, face_embedding in enumerate(face_embeddings or []):
                            owner_distance = self._cosine_distance(
                                face_embedding, owner_embedding
                            )
                            if (
                                owner_distance <= self.THRESHOLD_REVIEW
                                and face_index not in owner_face_indices
                            ):
                                updated_matches.append({
                                    "person": owner_person,
                                    "distance": owner_distance,
                                    "verified": owner_distance <= self.THRESHOLD_SECURE,
                                    "face_index": face_index,
                                    "match_type": (
                                        "secure"
                                        if owner_distance <= self.THRESHOLD_SECURE
                                        else "review"
                                    ),
                                    "match_source": "postmotor_reference_collision_owner",
                                })
                                owner_face_indices.add(face_index)
                if updated_matches:
                    match_map[existing_key] = updated_matches
                else:
                    match_map.pop(existing_key, None)

            audit = {
                "persona": target_name,
                "referencia": target_person.get("reference_value", ""),
                "foto_referencia": self._relative_to_workspace(original_path) if original_path else "",
                "cruzada_con": owner_name,
                "referencia_distancia_a_otro_ancla": round(float(collision["reference_distance"]), 4),
                "distancia_a_grupo_cruzado": round(float(collision["target_to_owner_group"]), 4),
                "distancia_a_grupo_numerico_propio": round(float(collision["own_distance"]), 4),
                "fuente_grupo": str(collision["owner_cluster"].get("source", "ventana_numerica")),
                "grupo_reparacion": f"{repair_cluster['numbers'][0]}-{repair_cluster['numbers'][-1]}",
                "fotos_grupo_reparacion": [
                    self._relative_to_workspace(path) for path in repair_cluster["paths"]
                ],
                "accion": (
                    "Referencia cruzada reparada post-motor con el cluster numérico "
                    "coherente; el motor de reconocimiento no se modificó."
                ),
            }
            audits.append(audit)
            repaired_folders.add(target_folder)

            for detail in report.get("seleccion_rostros_referencia") or []:
                if detail.get("persona") == target_name:
                    detail.update({
                        "referencia_cruzada_con": owner_name,
                        "referencia_reparada": True,
                        "referencia_fuente_postmotor": audit["grupo_reparacion"],
                        "referencia_embedding_original_distancia": round(
                            float(collision["reference_distance"]), 4
                        ),
                    })

    @staticmethod
    def _lookup_face_embeddings(
        face_embeddings: Dict[Path, List[list]],
        path: Optional[Path],
    ) -> List[list]:
        if path is None:
            return []
        direct = face_embeddings.get(path)
        if direct is not None:
            return direct
        resolved = path.resolve(strict=False)
        direct = face_embeddings.get(resolved)
        if direct is not None:
            return direct
        for key, value in face_embeddings.items():
            try:
                if Path(key).resolve(strict=False) == resolved:
                    return value
            except Exception:
                continue
        return []

    def _detect_weak_reference_orphan_groups(
        self,
        people: List[Dict[str, Any]],
        image_paths: List[Path],
        copied_sources: set,
        photo_face_embeddings: Dict[Path, List[list]],
        report: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Post-motor audit: report coherent ignored groups for weak refs.

        This never assigns photos to a student. It only surfaces cases like a
        reference with zero visual support plus ignored portraits that agree with
        each other, so the user can correct the reference or review manually.
        """
        if not photo_face_embeddings:
            return [], []

        selection_by_person = {
            str(item.get("persona", "")): item
            for item in (report.get("seleccion_rostros_referencia") or [])
            if isinstance(item, dict)
        }
        weak_entries: List[Dict[str, Any]] = []
        orphan_groups: List[Dict[str, Any]] = []
        copied_resolved = {
            Path(path).resolve(strict=False) for path in (copied_sources or set())
        }

        candidate_items: List[Dict[str, Any]] = []
        for image_path in image_paths:
            resolved = image_path.resolve(strict=False)
            if resolved in copied_resolved:
                continue
            embeddings = self._lookup_face_embeddings(photo_face_embeddings, image_path)
            if not embeddings:
                continue
            number = self._last_number(image_path.stem)
            if number is None:
                continue
            for face_index, embedding in enumerate(embeddings):
                candidate_items.append({
                    "path": resolved,
                    "embedding": embedding,
                    "face_index": face_index,
                    "number": number,
                    "stem": image_path.stem.lower(),
                    "distance": 0.0,
                })

        if not candidate_items:
            return [], []

        for person in people:
            detail = selection_by_person.get(str(person.get("display_name", "")))
            if not detail:
                continue
            try:
                support = int(detail.get("soporte_fotos") or 0)
            except (TypeError, ValueError):
                support = 0
            if support > 0:
                continue

            reference_path = person.get("reference_path")
            reference_number = self._last_number(
                person.get("reference_value")
                or (Path(reference_path).stem if reference_path else "")
            )
            weak_entry = {
                "persona": person.get("display_name", ""),
                "referencia": person.get("reference_value", ""),
                "foto_referencia": detail.get("foto", ""),
                "soporte_fotos": support,
                "score_referencia": detail.get("score", 0),
                "motivo": "referencia_sin_soporte_visual",
                "accion": "No se asignaron fotos automaticamente; revisar grupos huerfanos.",
                "grupos_candidatos_detectados": 0,
            }
            weak_entries.append(weak_entry)
            if reference_number is None:
                continue

            nearby = [
                item for item in candidate_items
                if abs(int(item["number"]) - reference_number)
                <= self.WEAK_REFERENCE_ORPHAN_WINDOW
            ]
            if not nearby:
                continue

            components = self._cluster_embedding_items(
                nearby, max_distance=self.WEAK_REFERENCE_ORPHAN_MAX_DISTANCE)
            reported_for_person = 0
            ref_embeddings = self._lookup_face_embeddings(
                photo_face_embeddings,
                Path(reference_path) if reference_path else None,
            )

            for component in components:
                by_stem: Dict[str, Dict[str, Any]] = {}
                for item in component:
                    current = by_stem.get(item["stem"])
                    path_text = str(item["path"]).lower()
                    prefers_corrected = "corregid" in path_text
                    if current is None or (
                        prefers_corrected and "corregid" not in str(current["path"]).lower()
                    ):
                        by_stem[item["stem"]] = item
                representatives = list(by_stem.values())
                if len(representatives) < self.WEAK_REFERENCE_ORPHAN_MIN_STEMS:
                    continue

                pair_distances = []
                for left in range(len(representatives)):
                    for right in range(left + 1, len(representatives)):
                        pair_distances.append(self._cosine_distance(
                            representatives[left]["embedding"],
                            representatives[right]["embedding"],
                        ))
                ref_distances = []
                for ref_embedding in ref_embeddings:
                    for item in representatives:
                        ref_distances.append(self._cosine_distance(
                            ref_embedding, item["embedding"]))

                numbers = sorted({int(item["number"]) for item in representatives})
                all_paths = sorted({
                    self._relative_to_workspace(Path(item["path"]))
                    for item in component
                })
                group = {
                    "persona_sugerida": person.get("display_name", ""),
                    "referencia": person.get("reference_value", ""),
                    "foto_referencia": detail.get("foto", ""),
                    "motivo": (
                        "grupo_ignorado_coherente_cerca_de_referencia_debil"
                    ),
                    "accion": (
                        "No asignado automaticamente; confirmar referencia o asignar manualmente."
                    ),
                    "cantidad_fotos_unicas": len(representatives),
                    "cantidad_archivos_relacionados": len(all_paths),
                    "numeros": numbers,
                    "rango_numerico": (
                        f"{numbers[0]}-{numbers[-1]}" if numbers else ""
                    ),
                    "distancia_promedio_grupo": round(
                        sum(pair_distances) / max(1, len(pair_distances)), 4),
                    "distancia_minima_a_referencia": (
                        round(min(ref_distances), 4) if ref_distances else None
                    ),
                    "fotos": all_paths,
                }
                orphan_groups.append(group)
                reported_for_person += 1
                if reported_for_person >= 3:
                    break

            weak_entry["grupos_candidatos_detectados"] = reported_for_person

        return weak_entries, orphan_groups

    @staticmethod
    def _path_lookup_key(value: Any) -> str:
        return str(value or "").replace("\\", "/").lower()

    def _deliver_weak_reference_orphan_groups(
        self,
        people: List[Dict[str, Any]],
        image_paths: List[Path],
        orphan_groups: List[Dict[str, Any]],
        copied_sources: set,
        assigned_sources: set,
        report: Dict[str, Any],
        cr2_twin_of: Dict[Path, List[Path]],
        cr2_delivery_index: Optional[Dict[str, List[Path]]] = None,
    ) -> None:
        """Post-motor delivery for confirmed weak-reference orphan groups.

        The recognition engine and thresholds are not changed here. This only
        delivers groups already detected as coherent ignored photos for a weak
        reference, and reports every file as a post-motor rescue.
        """
        if not orphan_groups:
            return

        people_by_name = {
            str(person.get("display_name", "")): person
            for person in people
        }
        path_lookup: Dict[str, Path] = {}
        for path in image_paths:
            resolved = path.resolve(strict=False)
            keys = {
                str(path),
                str(resolved),
                self._relative_to_workspace(path),
                self._relative_to_workspace(resolved),
            }
            for key in keys:
                path_lookup[self._path_lookup_key(key)] = path

        def resolve_report_path(value: Any) -> Optional[Path]:
            key = self._path_lookup_key(value)
            if key in path_lookup:
                return path_lookup[key]
            raw = Path(str(value or ""))
            candidates = [raw]
            if not raw.is_absolute():
                candidates.append(self.workspace_path / raw)
            for candidate in candidates:
                resolved = candidate.resolve(strict=False)
                if resolved.exists():
                    return resolved
                found = path_lookup.get(self._path_lookup_key(resolved))
                if found is not None:
                    return found
            return None

        def candidate_rank(path: Path) -> Tuple[int, int]:
            text = str(path).lower()
            corrected = 1 if "corregid" in text else 0
            non_raw = 0 if path.suffix.lower() in self.RAW_EXTENSIONS else 1
            return corrected, non_raw

        removed_from_ignored: set[str] = set()
        rescues = report.setdefault("fotos_rescatadas_referencia_debil", [])

        def group_stem_key(group: Dict[str, Any]) -> Tuple[str, ...]:
            stems = {
                Path(str(item or "")).stem.lower()
                for item in (group.get("fotos") or [])
                if str(item or "").strip()
            }
            return tuple(sorted(stems))

        def numeric_distance_to_group(group: Dict[str, Any]) -> int:
            reference_number = self._last_number(group.get("referencia", ""))
            numbers = []
            for value in (group.get("numeros") or []):
                try:
                    numbers.append(int(value))
                except (TypeError, ValueError):
                    continue
            if reference_number is None or not numbers:
                return 999999
            return min(abs(number - reference_number) for number in numbers)

        def group_rank(group: Dict[str, Any]) -> Tuple[float, ...]:
            """Rank duplicate weak-reference claims without touching recognition.

            Visual distance wins when the weak reference is still usable.  If the
            reference is visually weak for every claimant, fall back to the
            reference number as a delivery tiebreaker so a crossed filename does
            not let the first claimant steal the whole coherent group.
            """
            reference_number = self._last_number(group.get("referencia", ""))
            numbers = []
            for value in (group.get("numeros") or []):
                try:
                    numbers.append(int(value))
                except (TypeError, ValueError):
                    continue
            contains_reference = 0 if reference_number in set(numbers) else 1
            numeric_gap = numeric_distance_to_group(group)
            try:
                ref_distance = float(group.get("distancia_minima_a_referencia"))
            except (TypeError, ValueError):
                ref_distance = 999.0
            try:
                group_distance = float(group.get("distancia_promedio_grupo"))
            except (TypeError, ValueError):
                group_distance = 999.0
            visual_reference_is_useful = 0 if ref_distance <= self.THRESHOLD_REVIEW else 1
            # Lower tuple is better.  When the weak reference is not visually
            # useful, numeric ownership is only a post-motor tiebreaker.
            if visual_reference_is_useful == 0:
                return (
                    0,
                    ref_distance,
                    float(contains_reference),
                    float(numeric_gap),
                    group_distance,
                    -float(len(numbers)),
                )
            return (
                1,
                float(contains_reference),
                float(numeric_gap),
                group_distance,
                ref_distance,
                -float(len(numbers)),
            )

        # Arbitraje global por STEM, no solo por grupos exactamente iguales.
        # Esto elimina la dependencia del orden cuando dos grupos se traslapan
        # parcialmente (por ejemplo 2412-2413 frente a 2412-2415).
        def claim_rank(group: Dict[str, Any]) -> Tuple[Any, ...]:
            return (*group_rank(group), str(group.get("persona_sugerida", "")).lower())

        stem_claims: Dict[str, List[Dict[str, Any]]] = {}
        for group in orphan_groups:
            group["_delivery_fotos"] = list(group.get("fotos") or [])
            for stem in group_stem_key(group):
                stem_claims.setdefault(stem, []).append(group)

        for stem, claims in stem_claims.items():
            if len(claims) <= 1:
                continue
            winner = min(claims, key=claim_rank)
            winner.setdefault("desempates_globales_referencia_debil", []).append({
                "stem": stem,
                "ganador": winner.get("persona_sugerida", ""),
                "candidatos": [claim.get("persona_sugerida", "") for claim in claims],
                "criterio": (
                    "rostro_si_la_referencia_es_util; numero_raiz_y_coherencia "
                    "como desempate postmotor; nunca orden de carpeta"
                ),
            })
            for claim in claims:
                if claim is winner:
                    continue
                claim["_delivery_fotos"] = [
                    item for item in claim.get("_delivery_fotos") or []
                    if Path(str(item)).stem.lower() != stem
                ]
                claim.setdefault("solapamientos_resueltos", []).append({
                    "stem": stem,
                    "ganador": winner.get("persona_sugerida", ""),
                    "criterio": "desempate_global_postmotor",
                })
                claim["grupo_ganador"] = winner.get("persona_sugerida", "")
                claim["accion"] = (
                    "No duplicado: el stem traslapado fue asignado al ganador "
                    "del desempate global post-motor."
                )
                claim["motivo_no_entregado"] = "superado_por_desempate_global"
                if not claim.get("_delivery_fotos"):
                    claim["resuelto_por_otro_grupo"] = True

        for group in orphan_groups:
            delivery_fotos = group.get("_delivery_fotos") or []
            if not delivery_fotos:
                group["entregado_postmotor"] = False
                group["archivos_entregados_postmotor"] = []
                group["fotos_fuente_entregadas_postmotor"] = []
                group["cr2_gemelos_copiados_postmotor"] = 0
                group.pop("_delivery_fotos", None)
                continue

            person = people_by_name.get(str(group.get("persona_sugerida", "")))
            if not person:
                group["entregado_postmotor"] = False
                group["motivo_no_entregado"] = "persona_no_encontrada"
                continue

            related_paths: List[Path] = []
            by_stem: Dict[str, Path] = {}
            for item in delivery_fotos:
                path = resolve_report_path(item)
                if path is None:
                    continue
                related_paths.append(path)
                stem = path.stem.lower()
                current = by_stem.get(stem)
                if current is None or candidate_rank(path) > candidate_rank(current):
                    by_stem[stem] = path

            delivered_targets: List[str] = []
            delivered_sources: List[str] = []
            cr2_copied = 0

            for source in by_stem.values():
                resolved = source.resolve(strict=False)
                if resolved in copied_sources:
                    continue
                copy_result = self._copy_image_once(source, person["folder_path"])
                if copy_result["status"] not in {"copied", "reused"}:
                    if copy_result["status"] == "conflict":
                        report["conflicts"].append(copy_result)
                    elif copy_result["status"] == "error":
                        report["errors"].append(copy_result["message"])
                    continue

                copied_sources.add(resolved)
                assigned_sources.add(resolved)
                source_rel = self._relative_to_workspace(source)
                target_rel = self._relative_to_workspace(Path(copy_result["path"]))
                report[copy_result["status"]].append(target_rel)
                report["fotos_por_persona"][person["display_name"]].append(target_rel)
                delivered_sources.append(source_rel)
                delivered_targets.append(target_rel)
                if copy_result["status"] == "copied":
                    report["total_fotos_copiadas"] += 1

                twin_count = self._copy_cr2_twin(
                    source, person["folder_path"], cr2_twin_of, cr2_delivery_index)
                report["cr2_gemelos_copiados"] += twin_count
                cr2_copied += twin_count

                rescues.append({
                    "foto": source_rel,
                    "foto_entregada": target_rel,
                    "alumno": person["display_name"],
                    "referencia": group.get("referencia", ""),
                    "rango_numerico": group.get("rango_numerico", ""),
                    "distancia_promedio_grupo": group.get("distancia_promedio_grupo"),
                    "distancia_minima_a_referencia": group.get("distancia_minima_a_referencia"),
                    "cr2_gemelo_copiado": twin_count,
                    "motivo": "rescate_postmotor_referencia_debil",
                })

            for path in related_paths:
                removed_from_ignored.add(self._relative_to_workspace(path))

            group["entregado_postmotor"] = bool(delivered_targets)
            group["archivos_entregados_postmotor"] = delivered_targets
            group["fotos_fuente_entregadas_postmotor"] = delivered_sources
            group["cr2_gemelos_copiados_postmotor"] = cr2_copied
            group.pop("_delivery_fotos", None)
            if group.get("desempates_globales_referencia_debil"):
                group["desempate_global_referencia_debil"] = {
                    "ganador": group.get("persona_sugerida", ""),
                    "candidatos": sorted({
                        candidate
                        for entry in group["desempates_globales_referencia_debil"]
                        for candidate in entry.get("candidatos", [])
                    }),
                    "criterio": "grupo global por stem; no depende del orden de carpeta",
                    "stems": group["desempates_globales_referencia_debil"],
                }
                group.pop("desempates_globales_referencia_debil", None)
            if delivered_targets:
                group["accion"] = (
                    "Entregado automaticamente por rescate post-motor de referencia debil; "
                    "el motor de reconocimiento no se modifico."
                )
            else:
                already_delivered_elsewhere = bool(by_stem) and all(
                    source.resolve(strict=False) in copied_sources
                    or source.resolve(strict=False) in assigned_sources
                    for source in by_stem.values()
                )
                if already_delivered_elsewhere:
                    group["resuelto_por_otro_grupo"] = True
                    group["accion"] = (
                        "No duplicado: esas fotos ya fueron entregadas al grupo "
                        "ganador post-motor."
                    )
                    group["motivo_no_entregado"] = "resuelto_por_otro_grupo"
                else:
                    group["motivo_no_entregado"] = "sin_archivos_entregables"

        if removed_from_ignored:
            for key in ("fotos_no_identificadas", "fotos_ignoradas_no_asignadas"):
                report[key] = [
                    item for item in (report.get(key) or [])
                    if item not in removed_from_ignored
                ]

    def _split_cr2_twins(self, image_paths: List[Path]):
        """Optimización de tiempo (NO toca el motor ni el reconocimiento):
        si IMG.JPG e IMG.CR2 están en la MISMA carpeta con el MISMO stem, se
        analiza SOLO el JPG (es la misma foto; DeepFace de todos modos convierte
        el CR2 a JPG antes de reconocer). El CR2 gemelo se recuerda para copiarlo
        junto al JPG si éste se clasifica -> mismos archivos entregados, sin perder
        RAW, con la mitad del trabajo. CR2 SIN gemelo JPG se analiza como siempre.
        Devuelve (analyzed_paths, cr2_twin_of, cr2_omitidos)."""
        prefer = (".jpg", ".jpeg", ".png")
        by_key: Dict[tuple, Dict[str, Path]] = {}
        for p in image_paths:
            by_key.setdefault((str(p.parent).lower(), p.stem.lower()), {})[p.suffix.lower()] = p
        analyzed: List[Path] = []
        cr2_twin_of: Dict[Path, List[Path]] = {}
        omitidos = 0
        for p in image_paths:
            if p.suffix.lower() in self.RAW_EXTENSIONS:
                twins = by_key.get((str(p.parent).lower(), p.stem.lower()), {})
                jpg = next((twins[e] for e in prefer if e in twins), None)
                if jpg is not None:  # CR2 con gemelo JPG en la MISMA carpeta -> no analizar
                    cr2_twin_of.setdefault(jpg.resolve(strict=False), []).append(p)
                    omitidos += 1
                    continue
            analyzed.append(p)
        for twins in cr2_twin_of.values():
            twins.sort(key=lambda path: (path.suffix.lower(), str(path).lower()))
        return analyzed, cr2_twin_of, omitidos

    def _build_cr2_delivery_index(self, image_paths: List[Path]) -> Dict[str, List[Path]]:
        """Indexa CR2 por stem en toda la seleccion para entrega RAW.

        No cambia que foto analiza el motor. Solo permite encontrar el RAW cuando
        el JPG clasificado viene de otra carpeta, por ejemplo FOTOS CORREGIDAS.
        """
        index: Dict[str, List[Path]] = {}
        for p in image_paths:
            if p.suffix.lower() not in self.RAW_EXTENSIONS:
                continue
            key = p.stem.lower()
            index.setdefault(key, []).append(p)
        for candidates in index.values():
            candidates.sort(key=lambda path: str(path).lower())
        return index

    def _copy_cr2_twin(self, image_path: Path, dest_dir: Path,
                       cr2_twin_of: Dict[Path, List[Path]],
                       cr2_delivery_index: Optional[Dict[str, List[Path]]] = None) -> int:
        """Copia el CR2 gemelo de un JPG ya clasificado a la MISMA carpeta de
        salida (no perder RAW). Solo entrega el archivo; no analiza nada. Devuelve
        1 si copió/reutilizó el gemelo, 0 si no hay gemelo o falló."""
        resolved_image = image_path.resolve(strict=False)
        direct = cr2_twin_of.get(resolved_image) or []
        # Compatibilidad defensiva con mapas Path -> Path de versiones previas.
        if isinstance(direct, Path):
            direct = [direct]
        twins = list(direct)
        seen = {path.resolve(strict=False) for path in twins}
        if cr2_delivery_index:
            by_extension: Dict[str, List[Path]] = {}
            for candidate in cr2_delivery_index.get(image_path.stem.lower(), []):
                resolved_candidate = candidate.resolve(strict=False)
                if resolved_candidate == resolved_image or resolved_candidate in seen:
                    continue
                seen.add(resolved_candidate)
                by_extension.setdefault(candidate.suffix.lower(), []).append(candidate)
            direct_extensions = {path.suffix.lower() for path in twins}
            for extension, candidates in by_extension.items():
                # Una coincidencia por formato es determinista; dos CR3 o dos
                # CR2 con el mismo stem siguen siendo ambiguos y no se adivinan.
                if extension not in direct_extensions and len(candidates) == 1:
                    twins.append(candidates[0])
        copied = 0
        for twin in twins:
            try:
                res = self._copy_image_once(twin, dest_dir)
                if res.get("status") in ("copied", "reused"):
                    copied += 1
                    format_name = twin.suffix.lower().lstrip(".")
                    self._delivery_stats["raw_twins"] = (
                        self._delivery_stats.get("raw_twins", 0) + 1
                    )
                    format_key = f"{format_name}_twins"
                    self._delivery_stats[format_key] = (
                        self._delivery_stats.get(format_key, 0) + 1
                    )
            except Exception:
                continue
        return copied

    def _copy_image_once(self, source: Path, destination_dir: Path) -> Dict[str, str]:
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            target = destination_dir / source.name
            if target.exists():
                if self._same_file(source, target):
                    return {"path": str(target), "status": "reused", "message": "La foto ya existía idéntica, se reutilizó."}
                return {"path": str(target), "status": "conflict", "message": f"Conflicto: '{target.name}' ya existe con contenido distinto."}
            delivery_mode = os.environ.get("FACESYNC_DELIVERY_MODE", "auto").strip().lower()
            if delivery_mode in {"auto", "link", "hardlink"}:
                try:
                    os.link(source, target)
                    self._delivery_stats["hardlinks"] += 1
                    return {
                        "path": str(target),
                        "status": "copied",
                        "message": "Foto entregada mediante enlace NTFS sin duplicar datos.",
                        "delivery_mode": "hardlink",
                    }
                except OSError:
                    self._delivery_stats["link_fallbacks"] += 1
                    if delivery_mode in {"link", "hardlink"}:
                        logger.warning("Hardlink no disponible; usando copia fisica: %s", source)
            shutil.copy2(source, target)
            self._delivery_stats["physical_copies"] += 1
            return {
                "path": str(target), "status": "copied",
                "message": "Foto copiada.", "delivery_mode": "physical_copy",
            }
        except Exception as exc:
            return {"path": str(destination_dir / source.name), "status": "error", "message": str(exc)}

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        try:
            try:
                if os.path.samefile(left, right):
                    return True
            except OSError:
                pass
            if left.stat().st_size != right.stat().st_size:
                return False
            with left.open("rb") as left_file, right.open("rb") as right_file:
                while True:
                    left_chunk = left_file.read(4 * 1024 * 1024)
                    right_chunk = right_file.read(4 * 1024 * 1024)
                    if left_chunk != right_chunk:
                        return False
                    if not left_chunk:
                        return True
        except OSError:
            return False

    def _write_reports(self, report: Dict[str, Any], destination_folder: Path) -> Dict[str, str]:
        json_path = destination_folder / "_reporte_facesync.json"
        txt_path = destination_folder / "_reporte_facesync.txt"
        xlsx_path = destination_folder / "_reporte_facesync.xlsx"

        serializable = self._json_safe(report)
        json_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

        diag = report.get("diagnostico", {})
        lines = [
            "FaceSync reference_face_matching report",
            f"table_path: {report.get('table_path')}",
            f"source_folder: {report.get('source_folder')}",
            f"destination_folder: {report.get('destination_folder')}",
            f"total_personas: {report.get('total_personas')}",
            f"referencias_encontradas: {report.get('referencias_encontradas')}",
            f"referencias_faltantes: {len(report.get('referencias_faltantes') or [])}",
            f"total_fotos_analizadas: {report.get('total_fotos_analizadas')}",
            f"total_fotos_copiadas: {report.get('total_fotos_copiadas')}",
            f"raw_detectadas: {report.get('raw_metrics', {}).get('raw_detectadas', 0)}",
            f"cr2_detectadas: {report.get('raw_metrics', {}).get('cr2_detectadas', 0)}",
            f"cr3_detectadas: {report.get('raw_metrics', {}).get('cr3_detectadas', 0)}",
            f"raw_errores: {report.get('raw_metrics', {}).get('raw_errores', 0)}",
            f"raw_gemelos_copiados: {report.get('raw_gemelos_copiados', 0)}",
            f"cr2_gemelos_copiados: {report.get('cr2_gemelos_copiados', 0)}",
            f"cr3_gemelos_copiados: {report.get('cr3_gemelos_copiados', 0)}",
            f"fotos_ignoradas_no_asignadas: {len(report.get('fotos_ignoradas_no_asignadas') or [])}",
            f"fotos_sin_candidato: {len(report.get('fotos_sin_candidato') or [])}",
            (lambda dud: f"fotos_dudosas: {len(dud)} (entregadas a su mejor alumno: "
                         f"{sum(1 for e in dud if e.get('asignada_a'))}, en Pendientes: "
                         f"{sum(1 for e in dud if not e.get('asignada_a'))})")(report.get('fotos_dudosas') or []),
            f"fotos_multi_alumno: {len(report.get('fotos_multi_alumno') or [])}",
            (lambda conf: f"conflictos_identidad: {len(conf)} (entregados al más cercano: "
                          f"{sum(1 for e in conf if e.get('asignada_a'))}, en revisión: "
                          f"{sum(1 for e in conf if not e.get('asignada_a'))})")(report.get('conflictos_identidad') or []),
            f"rescatadas_por_galeria: {len(report.get('fotos_rescatadas_galeria') or [])}",
            f"rescatadas_cr3_fullraw: {len(report.get('fotos_rescatadas_cr3_fullraw') or [])}",
            f"cr3_fullraw_objetivos: {report.get('cr3_dual_decode', {}).get('targets', 0)}",
            f"cr3_fullraw_procesadas: {report.get('cr3_dual_decode', {}).get('fullraw_processed', 0)}",
            f"cr3_fullraw_cache_hits: {report.get('cr3_dual_decode', {}).get('fullraw_cache_hits', 0)}",
            f"selector_referencia_cr3_activo: {report.get('cr3_reference_selector', {}).get('enabled', False)}",
            f"referencias_cr3_promovidas: {report.get('cr3_reference_selector', {}).get('promoted_references', 0)}",
            f"referencias_cr3_conservadas: {report.get('cr3_reference_selector', {}).get('preserved_references', 0)}",
            f"arranque_galeria_cr3_activo: {report.get('cr3_gallery_bootstrap', {}).get('enabled', False)}",
            f"alimentadores_galeria_cr3_preview: {report.get('cr3_gallery_bootstrap', {}).get('preview', {}).get('feeders', 0)}",
            f"alimentadores_galeria_cr3_fullraw: {report.get('cr3_gallery_bootstrap', {}).get('fullraw', {}).get('feeders', 0)}",
            f"arbitro_cr3_activo: {report.get('cr3_route_arbiter', {}).get('enabled', False)}",
            f"arbitro_cr3_acuerdos: {report.get('cr3_route_arbiter', {}).get('agreements', 0)}",
            f"arbitro_cr3_rescates: {report.get('cr3_route_arbiter', {}).get('rescues_accepted', 0)}",
            f"arbitro_cr3_contradicciones: {report.get('cr3_route_arbiter', {}).get('blocked_contradictions', 0)}",
            f"rescatadas_referencia_debil: {len(report.get('fotos_rescatadas_referencia_debil') or [])}",
            f"referencias_cruzadas_reparadas: {len(report.get('auditoria_referencias_cruzadas') or [])}",
            f"codigos_repetidos_historicos: {report.get('identity_registry', {}).get('codigos_repetidos_historicos', [])}",
            f"referencias_historicas_auditadas: {len(report.get('auditoria_referencias_historicas') or [])}",
            f"identidades_registradas: {len(report.get('identidades_registradas') or [])}",
            f"referencias_debiles: {len(report.get('referencias_debiles') or [])}",
            f"grupos_huerfanos_referencia_debil: {len(report.get('grupos_huerfanos_referencia_debil') or [])}",
            f"gallery_feeds: {report.get('gallery_stats', {}).get('gallery_feeds', 0)}",
            f"codigos_repetidos_excel: {report.get('smart_reference', {}).get('codigos_repetidos_excel', [])}",
            f"indice_facial_activo: {report.get('facial_index_stats', {}).get('enabled', False)}",
            f"indice_facial_seleccionadas: {report.get('facial_index_stats', {}).get('selected_photos', 0)}",
            f"indice_facial_reduccion: {report.get('facial_index_stats', {}).get('reduction_percent', 0)}%",
            f"scan_seconds: {report.get('performance_stats', {}).get('scan_seconds', 0)}",
            f"preview_decode_wait_seconds: {report.get('facial_index_stats', {}).get('preview_decode_wait_seconds', 0)}",
            f"preview_inference_seconds: {report.get('facial_index_stats', {}).get('preview_inference_seconds', 0)}",
            f"arcface_batch_calls: {report.get('facial_index_stats', {}).get('arcface_batch_calls', 0)}",
            f"candidate_extraction_seconds: {report.get('performance_stats', {}).get('candidate_extraction_seconds', 0)}",
            f"performance_backend: {report.get('performance_stats', {}).get('backend', '')}",
            f"gpu_fallbacks: {report.get('performance_stats', {}).get('gpu_fallbacks', 0)}",
            f"hardlinks: {report.get('delivery_stats', {}).get('hardlinks', 0)}",
            f"physical_copies: {report.get('delivery_stats', {}).get('physical_copies', 0)}",
            f"referencias_invalidas: {len(report.get('referencias_invalidas') or [])}",
            f"errores_deepface: {len(report.get('errores_deepface') or [])}",
            f"errores_imagen: {len(report.get('errores_imagen') or [])}",
            f"porcentaje_entrega: {diag.get('porcentaje_entrega', 'N/A')}%",
            f"porcentaje_cobertura_origen: {diag.get('porcentaje_cobertura_origen', 'N/A')}%",
            f"porcentaje_clasificado: {diag.get('porcentaje_clasificado', 'N/A')}%",
            f"promedio_fotos_por_alumno: {diag.get('promedio_fotos_por_alumno', 'N/A')}",
            f"tiempo_total: {report.get('tiempo_total')}",
        ]
        # Append diagnostic warnings
        for warning in diag.get("advertencias", []):
            lines.append(f"ADVERTENCIA: {warning}")
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report_files = {
            "json": self._relative_to_workspace(json_path),
            "txt": self._relative_to_workspace(txt_path),
        }

        try:
            import pandas as pd

            summary = {key: value for key, value in serializable.items() if not isinstance(value, (list, dict))}
            summary.update(report.get("raw_metrics") or {})
            per_person = [
                {"persona": person, "foto": photo}
                for person, photos in (report.get("fotos_por_persona") or {}).items()
                for photo in photos
            ]
            with pd.ExcelWriter(xlsx_path) as writer:
                pd.DataFrame([summary]).to_excel(writer, sheet_name="Resumen", index=False)
                pd.DataFrame(per_person).to_excel(writer, sheet_name="Fotos por persona", index=False)
                pd.DataFrame(report.get("referencias_faltantes") or []).to_excel(writer, sheet_name="Referencias faltantes", index=False)
                pd.DataFrame(report.get("referencias_invalidas") or []).to_excel(writer, sheet_name="Referencias invalidas", index=False)
                pd.DataFrame({"foto": report.get("fotos_ignoradas_no_asignadas") or []}).to_excel(writer, sheet_name="Ignoradas no asignadas", index=False)
                pd.DataFrame(report.get("fotos_dudosas") or []).to_excel(writer, sheet_name="Pendientes reales", index=False)
                pd.DataFrame(report.get("fotos_sin_candidato") or []).to_excel(writer, sheet_name="Sin candidato", index=False)
                pd.DataFrame(report.get("fotos_multi_alumno") or []).to_excel(writer, sheet_name="Multi-alumno", index=False)
                pd.DataFrame(report.get("conflictos_identidad") or []).to_excel(writer, sheet_name="Conflictos identidad", index=False)
                pd.DataFrame(report.get("fotos_rescatadas_galeria") or []).to_excel(writer, sheet_name="Rescatadas galeria", index=False)
                pd.DataFrame(report.get("fotos_rescatadas_cr3_fullraw") or []).to_excel(writer, sheet_name="Rescatadas CR3 fullraw", index=False)
                pd.DataFrame(report.get("seleccion_referencia_cr3") or []).to_excel(writer, sheet_name="Selector referencia CR3", index=False)
                pd.DataFrame(report.get("arranque_galeria_cr3") or []).to_excel(writer, sheet_name="Arranque galeria CR3", index=False)
                pd.DataFrame(report.get("arbitraje_cr3") or []).to_excel(writer, sheet_name="Arbitraje CR3", index=False)
                pd.DataFrame(report.get("fotos_rescatadas_referencia_debil") or []).to_excel(writer, sheet_name="Rescatadas ref debil", index=False)
                pd.DataFrame(report.get("referencias_debiles") or []).to_excel(writer, sheet_name="Referencias debiles", index=False)
                pd.DataFrame(report.get("auditoria_referencias_cruzadas") or []).to_excel(writer, sheet_name="Referencias cruzadas", index=False)
                pd.DataFrame(report.get("auditoria_referencias_historicas") or []).to_excel(writer, sheet_name="Referencias historicas", index=False)
                pd.DataFrame(report.get("identidades_registradas") or []).to_excel(writer, sheet_name="Identidades registradas", index=False)
                pd.DataFrame(report.get("grupos_huerfanos_referencia_debil") or []).to_excel(writer, sheet_name="Grupos huerfanos", index=False)
                pd.DataFrame(report.get("errores_imagen") or []).to_excel(writer, sheet_name="Errores imagen", index=False)
            report_files["xlsx"] = self._relative_to_workspace(xlsx_path)
        except Exception as exc:
            logger.warning("No se pudo generar reporte Excel: %s", exc)

        return report_files

    def _sanitize_folder_name(self, value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = re.sub(r'[<>:"|?*]+', "", text)
        text = re.sub(r"[/\\]+", " - ", text)
        text = re.sub(r"\s*-\s*", " - ", text)
        text = re.sub(r"\s+", " ", text).strip().strip(".")
        if len(text) > 120:
            text = text[:120].rstrip()
        return text or "Sin nombre"

    @staticmethod
    def _normalize_reference_value(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = text.strip('"').strip("'")
        if re.fullmatch(r"\d+\.0+", text):
            text = text.split(".", 1)[0]
        return text

    @staticmethod
    def _norm_text(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _norm_reference_stem(cls, value: Any) -> str:
        text = cls._norm_text(value)
        if re.fullmatch(r"\d+ 0+", text.replace(".", " ")):
            return text.split()[0]
        return text

    def _relative_to_workspace(self, path: Path) -> str:
        try:
            return str(path.resolve(strict=False).relative_to(self.workspace_path)).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, set):
            return [cls._json_safe(item) for item in sorted(value)]
        return value

    # ========================================================
    # CANCELAR (PLACEHOLDER FUTURO)
    # ========================================================

    def cancel_current_task(self) -> Dict[str, Any]:
        self._cancel_event.set()
        self.status["message"] = "Cancelacion solicitada."
        return {
            "success": True,
            "message": "Cancelacion solicitada. Se detendra al terminar la foto o lote actual.",
        }

    # ========================================================
    # RESUMEN WORKSPACE
    # ========================================================

    def analyze_facesync_workspace(
        self,
        source_folder: str
    ) -> Dict[str, Any]:
        """
        Analiza una carpeta de imágenes.

        Ideal para:
        - Prevalidaciones
        - IA contextual
        - Diagnósticos automáticos

        Returns:
            Dict
        """

        try:

            secure_source = self._resolve_secure_path(
                source_folder
            )

            if not secure_source.exists():

                return {
                    "success": False,
                    "error": (
                        "La carpeta no existe."
                    )
                }

            extensions = self.IMAGE_EXTENSIONS

            image_count = 0

            folders = 0

            samples = []

            for root, dirs, files in os.walk(
                secure_source
            ):

                folders += len(dirs)

                for file in files:

                    ext = (
                        Path(file)
                        .suffix
                        .lower()
                    )

                    if ext in extensions:

                        image_count += 1

                        if len(samples) < 10:
                            samples.append(file)

            return {
                "success": True,
                "images": image_count,
                "folders": folders,
                "sample_images": samples,
                "workspace": str(secure_source)
            }

        except Exception as e:

            logger.exception(
                "Error analizando workspace"
            )

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # RESET STATUS
    # ========================================================

    def reset_status(self) -> Dict[str, Any]:
        """
        Reinicia estado interno.
        """

        self.status = {
            "running": False,
            "progress": 0,
            "message": "Idle",
            "started_at": None,
            "finished_at": None,
            "last_error": None
        }

        return {
            "success": True,
            "message": "Estado reiniciado."
        }
