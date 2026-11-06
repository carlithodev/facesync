# Módulo 6 — Registro histórico y caché consciente de ruta

## Resultado

El módulo quedó completado sin modificar RetinaFace, ArcFace, los umbrales generales, el árbitro CR3 del Módulo 5 ni la clasificación JPG/CR2.

La corrida real desde código fuente y la corrida desde el sidecar clasificaron correctamente `23/23` fotografías humanas CR3, con precisión y cobertura de `100%`, cero errores RAW y cero errores de imagen. El mismo sidecar aprobó después la regresión dorada CR2 con la firma exacta de `259` asignaciones.

## Persistencia implementada

- SQLite avanzó de esquema 1 a 2 mediante una expansión aditiva e idempotente.
- Se creó `identity_route_records`, una tabla exclusiva para identidades CR3 conscientes de ruta.
- La tabla histórica original permanece intacta para JPG, CR2 y registros anteriores.
- Preview y Full RAW pueden coexistir para la misma identidad, código y salón.
- Una nueva clasificación sólo sustituye el registro activo de la misma representación y versión.
- Los datos biométricos y rutas privadas continúan cifrados dentro del payload protegido.
- Los reportes sólo muestran metadatos seguros; no exportan embeddings.

Cada registro CR3 confirmado conserva código, alumno, salón, Excel, orígenes, fotografía raíz, hash, representación, versión, embedding principal, anclajes, cantidad de soportes, coherencia, fecha y cámara cuando está disponible.

## Aislamiento y compatibilidad

- Preview principal: `cr3_preview_v1`.
- Índice preview: `cr3_index_preview_v1`.
- Full RAW: `cr3_fullraw_v1`.
- Una referencia CR3 se compara únicamente con historial de la misma representación y versión.
- JPG/CR2 no comparan contra registros CR3 por ruta.
- Las carpetas y claves de caché CR2 no cambiaron.
- El historial se guarda por cuenta y fuera del árbol de caché desechable.
- Cerrar sesión, abrir de nuevo o limpiar el caché no elimina el historial de la cuenta.
- Otra cuenta no puede leer ni reutilizar esos registros.

## Evidencia real

El sidecar registró tres identidades-ruta con soporte múltiple:

- ATLETA, preview, 16 soportes.
- ATLETA, Full RAW, 14 soportes.
- BAILARINA, Full RAW, 2 soportes.

La ausencia de un registro preview para BAILARINA es deliberada: esa ruta no reunió el soporte mínimo. Full RAW sí lo reunió y quedó disponible para futuros códigos repetidos.

## Pruebas

- Suite completa: `129/129`.
- Migración v1→v2 con preservación del registro anterior.
- Reapertura idempotente del esquema v2.
- Coexistencia de preview y Full RAW sin sobrescritura cruzada.
- Segundo y tercer salón con el mismo código.
- Descarte de dos propietarios históricos anteriores antes de elegir una cara nueva.
- Bloqueo de comparaciones entre rutas o versiones incompatibles.
- Cierre/reapertura de sesión y aislamiento entre usuarios.
- Limpieza de embeddings y conversiones sin pérdida del historial.
- Compilación Python, Vite, Cargo `release` y PyInstaller.
- CR3 real desde fuente y sidecar: `23/23`.
- CR2 dorado desde el mismo sidecar: `259` asignaciones exactas.

## Artefactos

- `.codex_tmp/module6_cr3_20260811/natural_run_2/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module6_cr3_20260811/sidecar_run_1/MODULE_3_CR3_SIDECAR_EVALUATION.json`
- `.codex_tmp/module6_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.json`
- `.codex_tmp/module6_cr3_20260811/cr2_regression_sidecar_final/output/_reporte_facesync.json`

El sidecar y su copia de recursos Tauri comparten SHA-256 `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.

No se construyó el instalador final y no se inició el Módulo 7.
