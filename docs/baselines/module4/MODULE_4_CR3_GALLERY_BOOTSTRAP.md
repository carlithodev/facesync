# Módulo 4 — Arranque seguro de la galería CR3

## Resultado

El conjunto CR3 con referencias naturales pasó de `21/23` a `23/23` fotografías humanas correctas. La precisión se mantuvo en `100%` y la cobertura subió de `91.3%` a `100%`, sin asignaciones falsas, duplicadas ni ajenas al manifiesto.

| Identidad | Correctas | Reales | Precisión | Cobertura | Decisión |
|---|---:|---:|---:|---:|---|
| ATLETA | 20 | 20 | 100% | 100% | La galería existente ya era suficiente; el arranque no intervino |
| BAILARINA | 3 | 3 | 100% | 100% | Grupo Full RAW aceptado con dos fotografías distintas |
| Total | 23 | 23 | 100% | 100% | 0 falsos positivos y 0 omisiones |

## Arranque comprobado

- Preview y Full RAW se analizaron de forma independiente; sus embeddings no se mezclaron.
- Preview quedó bloqueado para BAILARINA porque sólo tenía una evidencia facial real y no cumplía el mínimo de dos fotografías distintas.
- Full RAW encontró un único grupo coherente compuesto por `_R4A4513.cr3` y `_R4A7192.cr3`.
- La distancia interna mediana y máxima del grupo fue `0.073525`.
- El grupo obtuvo margen `0.508913` frente a otras referencias y `0.817163` frente a otras galerías.
- Las dos imágenes se incorporaron como anclajes internos y luego fueron reevaluadas mediante las reglas existentes; no se asignaron directamente por la búsqueda amplia.
- El código y la fotografía raíz de BAILARINA continuaron siendo la autoridad.

## Hallazgo de seguridad y corrección

El primer enfoque completo recuperó las 23 fotografías humanas, pero también asignó los controles `IMG_0225.CR3` e `IMG_0226.CR3`, para una precisión de `92%`. Ese resultado fue rechazado.

El diagnóstico mostró que los embeddings de los controles eran anormalmente cercanos al grupo de BAILARINA, aunque el tamaño facial detectado era incompatible con la referencia y las fotografías reales. Se añadió una guarda conservadora de compatibilidad de escala facial únicamente al arranque CR3. Después de repetir la prueba, ambos controles quedaron fuera y el resultado pasó a `23/23` con precisión y cobertura de `100%`.

## Aislamiento y seguridad

- El arranque acepta exclusivamente archivos `.cr3`; JPG y CR2 son un no-op exacto.
- No se cambiaron RetinaFace, ArcFace ni los umbrales generales `0.28` y `0.40`.
- Se excluyen respaldos de imagen completa con confianza `0`.
- Una evidencia aislada no puede alimentar la galería.
- Los soportes deben proceder de al menos dos fotografías distintas.
- Las referencias de todos los alumnos se excluyen de los grupos candidatos.
- Se bloquean rostros ya asegurados por otra galería.
- Se exige coherencia interna, margen frente a otras referencias y margen frente a otras galerías.
- Preview y Full RAW conservan galerías y diagnósticos separados.
- Cada alimentador, bloqueo y fotografía reevaluada queda registrado en JSON, TXT y XLSX.

## Reproducibilidad y regresión

Las corridas limpias 4 y 5 produjeron exactamente el mismo resultado semántico:

- 23 correctas de 23.
- 23 entregadas.
- Precisión 100%.
- Cobertura 100%.
- Alimentadores `_R4A4513.cr3` y `_R4A7192.cr3`.
- Cero errores, duplicados y entregas desconocidas.

El sidecar PyInstaller reconstruido reprodujo el mismo resultado. Su SHA-256 es `73DA69994B63FD62AF893DBFCC182AFFC62C7C08555ED0C9B287AA3432832211`, idéntico al recurso sincronizado de Tauri.

La regresión dorada CR2 fue aprobada desde ese mismo ejecutable con la firma exacta de 259 asignaciones. También aprobaron 107/107 pruebas Python, 12/12 pruebas enfocadas, la compilación del código Python, Vite de producción y `cargo check --release`.

## Límite de la evidencia

El Módulo 4 cumple su condición de cierre sobre el conjunto real disponible. Ese conjunto contiene dos identidades humanas y no incluye una fotografía grupal real etiquetada. Los casos de rostro acompañante, identidad ajena, evidencia aislada, respaldo de confianza 0 y archivos JPG/CR2 están cubiertos por pruebas automatizadas, pero la paridad general de producción CR3 no se declarará hasta completar los módulos y conjuntos restantes.

Evidencia final:

- `.codex_tmp/module4_cr3_20260811/natural_run_4/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module4_cr3_20260811/natural_run_5/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module4_cr3_20260811/sidecar_run_1/MODULE_3_CR3_SIDECAR_EVALUATION.json`
- `.codex_tmp/module4_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.json`
- `.codex_tmp/module4_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.txt`
- `.codex_tmp/module4_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.xlsx`
- `.codex_tmp/module4_cr3_20260811/cr2_regression_sidecar_final/output/_reporte_facesync.json`
