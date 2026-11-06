# FaceSyncV2 — estado funcional

Actualizado: 2026-06-26.

Leyenda: `[x]` implementado y conectado · `[~]` parcial/limitado · `[ ]` pendiente.

## Login y cuentas

- [x] Login con Google OAuth mediante navegador del sistema.
- [x] Cuentas guardadas con avatar, nombre y correo.
- [x] Renovación de tokens expirados.
- [x] Confirmación antes de eliminar una cuenta guardada.
- [x] Tokens, configuración, perfiles y secreto OAuth fuera del código, en
  `%LOCALAPPDATA%/FaceSync`.
- [x] Compatibilidad de lectura con cuentas legacy.
- [x] Modo sin Drive cuando el usuario no concede ese alcance.

## Shell y navegación

- [x] React + Tauri con barra de título propia.
- [x] Navegación Workspace / Reportes / Exportaciones.
- [x] Cerrar sesión y volver al login.
- [x] Ventana redimensionable y maximizada después del login.
- [x] Estado de disponibilidad del motor.
- [x] Indicador de almacenamiento del workspace.

## Workspace

- [x] Explorador multi-root con carga perezosa por carpeta.
- [x] Agregar carpetas y archivos mediante selector nativo.
- [x] Drag & drop de archivos y carpetas.
- [x] Refrescar, crear carpeta, renombrar, abrir y eliminar.
- [x] Quitar una raíz del workspace sin borrar su contenido.
- [x] Borrado de elementos mediante Papelera de reciclaje.
- [x] Persistencia y restauración de raíces por cuenta.
- [x] Visor JPG/JPEG/PNG/GIF/BMP/WebP.
- [x] Zoom por botones, paneo, rotación y reset.
- [~] RAW/CR2 se procesa en el motor, pero no se previsualiza en React.
- [ ] Virtualización/paginación para carpetas con decenas de miles de entradas.

## Acciones rápidas

- [x] Leer Excel/CSV y mostrar columnas/filas.
- [x] Vista previa de carpetas desde una columna.
- [x] Creación de carpetas con nombres repetidos numerados.
- [x] Clasificación multi-origen mediante el motor moderno del FaceSync original.
- [x] Escaneo completo de fotos compatibles, sin ventana de ±15 posiciones.
- [x] Fotos grupales entregadas a cada persona reconocida.
- [x] Resolución contextual de códigos numéricos repetidos y reporte de empates.
- [x] Progreso real por fase conectado al modal directo.
- [x] Estado de proceso y errores visibles.
- [~] Cancelación cooperativa disponible desde el motor conversacional; el modal
  directo no puede interrumpir una inferencia nativa ya iniciada.
- [ ] Resumen visual final analizadas/clasificadas/pendientes dentro del modal.

## Asistente IA

- [x] Chat con historial, indicador de escritura e input.
- [x] Router local antes de usar red.
- [x] OpenAI como interpretación estructurada y Gemini como fallback.
- [x] Confirmación de acciones destructivas.
- [x] PlanGuard, ToolExecutionGate y SecurityManager.
- [x] Rutas limitadas a todas las raíces activas.
- [x] Memoria/contexto local.
- [x] Límite de concurrencia y timeouts del puente.
- [x] Recuperación visible cuando el sidecar se cierra.

## Reportes

- [x] Estadísticas reales.
- [x] Filtros por fecha, formato y carpeta.
- [x] Tabla paginada y detalle diferido.
- [x] Abrir con la aplicación del sistema.
- [x] Guardar una copia mediante diálogo nativo.
- [x] Estado vacío y corrección automática de página al filtrar.

## Exportaciones

- [x] Historial persistido de exportaciones.
- [x] Estadísticas y detalle.
- [x] Subida paralela a Google Drive.
- [x] Backoff para errores transitorios y cuotas.
- [x] Progreso y resumen final.
- [x] Soporte de rutas largas de Windows.
- [ ] Filtros/búsqueda avanzada en el historial.

## Seguridad y distribución

- [x] Sin credenciales ni tokens dentro del árbol del proyecto.
- [x] `.gitignore`, `.env.example` y OAuth de ejemplo.
- [x] Validación anti-traversal para cuentas y rutas del bridge.
- [x] CSP activa en Tauri.
- [x] Lectura base64 limitada a imágenes y 100 MB.
- [x] Embeddings cifrados con DPAPI del usuario de Windows.
- [x] Manifiesto Python reproducible.
- [x] Configuración PyInstaller para el sidecar instalable.
- [x] El bundle Tauri usa el sidecar empaquetado y excluye secretos.
- [~] Para generar un instalador todavía se necesita recrear `engine/env_ia`
  con Python 3.11; el entorno copiado actual conserva una referencia no portable.

## Verificación automática

- [x] Compilación Vite.
- [x] `cargo check` de Tauri/Rust.
- [x] Parseo sintáctico de todo el código Python.
- [x] Pruebas de aislamiento multi-root y traversal.
- [x] Prueba de cifrado/descifrado DPAPI.
- [ ] E2E con OAuth real, subida Drive y un lote facial representativo.
