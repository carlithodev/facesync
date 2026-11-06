# Módulo 5 — Decisión coordinada preview y Full RAW

## Resultado

La coordinación de rutas conservó `23/23` fotografías humanas correctas, con precisión y cobertura de `100%`. No aparecieron falsos positivos, omisiones, duplicados, entregas desconocidas, errores RAW ni errores de imagen.

El árbitro procesó 14 fotografías CR3 que necesitaban una segunda evaluación. Full RAW produjo cinco decisiones confirmadas y las cinco superaron la validación por rostro:

- `_R4A0055.cr3`
- `_R4A1229.cr3`
- `_R4A1272.cr3`
- `_R4A4513.cr3`
- `_R4A7192.cr3`

Las dos últimas conservaron los dos soportes de galería aceptados en el Módulo 4.

## Comportamiento implementado

- Preview y Full RAW continúan tomando decisiones independientes y sus embeddings nunca se mezclan.
- Una asignación preview segura es inmutable: Full RAW no puede sustituirla.
- Los rostros se relacionan entre rutas mediante cajas normalizadas, orientación, IoU y correspondencia uno a uno.
- En una fotografía grupal la decisión se toma por rostro, no por archivo.
- Full RAW sólo puede rescatar si tiene una distancia segura o consenso suficiente de galería.
- Una decisión directa exige margen frente a las demás identidades.
- Si preview y Full RAW proponen claramente personas diferentes para el mismo rostro, el rescate se bloquea.
- Si preview no detectó ningún rostro real y Full RAW contiene exactamente uno, se permite la segunda opinión únicamente si supera toda la evidencia de identidad.
- Una cara de respaldo con confianza `0` no cuenta como detección real.
- Cada acuerdo, conservación, rescate o bloqueo queda registrado en JSON, TXT y XLSX.

## Pruebas de seguridad

Las pruebas automatizadas cubren:

- No reemplazo de una asignación preview segura.
- Coincidencia de ambas rutas sin duplicar la entrega.
- Rescate Full RAW exclusivo.
- Consenso preview/Full RAW.
- Bloqueo por identidades distintas.
- Permiso cuando preview es ambiguo y Full RAW es claro.
- Bloqueo por margen insuficiente.
- Rescate por consenso de galería.
- Bloqueo de geometría ambigua en grupos.
- Recuperación independiente de distintas personas dentro de una foto grupal.
- Manejo de confianza `0`.
- Conservación de propietarios preview sin rostro localizable.
- No-op exacto para formatos distintos de CR3.

El árbitro aprobó `13/13` pruebas específicas y la suite completa aprobó `120/120`.

## Reproducibilidad y empaquetado

Dos corridas limpias consecutivas produjeron el mismo resultado semántico:

- 23 correctas de 23.
- 23 entregadas.
- Precisión 100%.
- Cobertura 100%.
- Los mismos cinco rescates Full RAW.
- Cero errores, duplicados y entregas desconocidas.

El sidecar PyInstaller reprodujo el mismo resultado y registró cinco filas de arbitraje. Su SHA-256 es `BA52A8684E6EADCFEB5E6C612BA250FA1BD402CD0B62935207D0953F512F410F`, idéntico al recurso sincronizado de Tauri.

La regresión dorada CR2 fue aprobada desde ese mismo ejecutable con la firma exacta de 259 asignaciones. También aprobaron la compilación del código Python, Vite de producción y `cargo check --release`.

No se construyó el instalador final.

## Límite de la evidencia

El conjunto real disponible contiene dos identidades humanas y no incluye una fotografía grupal real etiquetada ni un desacuerdo real entre rutas. Esos comportamientos están cubiertos mediante pruebas automatizadas, pero deben validarse con un conjunto real más amplio antes de declarar paridad CR3 general de producción.

Evidencia final:

- `.codex_tmp/module5_cr3_20260811/natural_run_1/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module5_cr3_20260811/natural_run_2/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module5_cr3_20260811/sidecar_run_1/MODULE_3_CR3_SIDECAR_EVALUATION.json`
- `.codex_tmp/module5_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.json`
- `.codex_tmp/module5_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.txt`
- `.codex_tmp/module5_cr3_20260811/sidecar_run_1/resultado/_reporte_facesync.xlsx`
- `.codex_tmp/module5_cr3_20260811/cr2_regression_sidecar_final/output/_reporte_facesync.json`
