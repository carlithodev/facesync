# FaceSyncV2 — paridad y compatibilidad

Actualizado: 2026-06-26.

## Alcance preservado

Los algoritmos de clasificación facial, umbrales, resolución de referencias,
copiado de resultados y generación de reportes son los mismos del flujo moderno
del proyecto original:

`FaceSyncCapabilities.run_reference_face_matching`.

La acción directa de React/Tauri ya entra a ese flujo mediante `classify_start`:
escanea el lote completo, combina múltiples orígenes, admite varias personas por
foto, resuelve referencias numéricas repetidas y genera reportes JSON/TXT/XLSX.
La cadena `motor_ia_fast → v3 → v2 → original` permanece disponible como código
legacy, pero ya no controla el botón principal de clasificación.

Sí cambiaron capas periféricas: almacenamiento de credenciales, validación de
rutas, comunicación Tauri/sidecar, Papelera de reciclaje, cifrado de caché y
empaquetado. Por ese motivo ya no es correcto afirmar que todos los archivos
mantienen el hash del proyecto original.

## Equivalencia funcional de React/Tauri

| Flujo | Implementación V2 | Estado |
|---|---|---|
| Cuentas guardadas | Rust + OAuth sidecar | Completo |
| OAuth nuevo/refresh | `oauth_service.py` | Completo |
| Explorador multi-root | `fs_*` + React | Completo |
| Drag & drop | evento Tauri | Completo |
| Crear/renombrar/eliminar | bridge confinado al workspace | Completo |
| Visor y paneo/zoom/rotación | React | Completo salvo preview RAW |
| Leer Excel/CSV | pandas/openpyxl | Completo |
| Crear carpetas | preview + confirmación | Completo |
| Clasificar fotos | motor moderno del FaceSync original | Completo |
| Chat local/OpenAI/Gemini | `chat_service.py` | Completo |
| Reportes | listado, filtros, detalle y copia | Completo |
| Drive | subida paralela y progreso | Completo |

Inicio y Resumen semanal permanecen fuera de la interfaz React por decisión de
alcance; sus módulos CustomTkinter siguen disponibles y compatibles.

## Compatibilidad de datos

- Las cuentas antiguas en `engine/usuarios` todavía pueden leerse.
- Las cuentas nuevas y las migradas viven en `%LOCALAPPDATA%/FaceSync/usuarios`.
- `.env` y `client_secret.json` viven en `%LOCALAPPDATA%/FaceSync/config`.
- El workspace guardado continúa en `%LOCALAPPDATA%/FaceSync/context`.
- Los embeddings legacy en JSON se leen y se reescriben cifrados con DPAPI.

## Verificación realizada

- Frontend Vite: compilación correcta.
- Tauri/Rust: `cargo check` correcto.
- Python: todos los módulos parsean sin errores sintácticos.
- Seguridad: pruebas de rutas internas/externas, raíces y nombres de cuenta.
- Paridad facial: pruebas de lote completo, multi-origen, fotos grupales y
  resolución conservadora de códigos repetidos.
- Dependencias JavaScript: auditoría npm sin vulnerabilidades conocidas al
  2026-06-26.

## Pruebas que requieren datos reales

Antes de publicar una versión final deben ejecutarse:

1. OAuth con una cuenta de prueba.
2. Exportación Drive con una carpeta pequeña.
3. Clasificación comparativa original/V2 sobre el mismo Excel y fotos.
4. Instalación limpia en una computadora sin el repositorio fuente.

El criterio de paridad facial debe comparar asignaciones, distancias, conteos y
reportes; no basta con que ambos procesos terminen sin error.
