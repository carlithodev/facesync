# Módulo 3 — Fortalecimiento de la referencia CR3

## Resultado

La clasificación con las referencias naturales pasó de `2/23` a `21/23` fotografías humanas correctas. La precisión permaneció en `100%`, la cobertura subió de `8.7%` a `91.3%` y no aparecieron asignaciones falsas, duplicadas ni ajenas al manifiesto.

| Identidad | Correctas | Reales | Precisión | Cobertura | Decisión |
|---|---:|---:|---:|---:|---|
| ATLETA | 20 | 20 | 100% | 100% | Ancla Full RAW promovida con 18 soportes |
| BAILARINA | 1 | 3 | 100% | 33.3% | Referencia raíz conservada por margen insuficiente |
| Total | 21 | 23 | 100% | 91.3% | 0 falsos positivos |

## Selección comprobada

- El código `9874` y `_R4A9874.cr3` siguieron siendo la autoridad de ATLETA.
- El selector eligió `_R4A1244.cr3` como ancla operativa, mediante la ruta Full RAW.
- El grupo de respaldo tuvo 18 fotografías, mediana interna `0.248159` y margen `0.393704` frente a otras identidades.
- La misma cara se relacionó entre preview y Full RAW mediante geometría con IoU `0.961732`.
- El código `6176` de BAILARINA no se forzó: el mejor grupo quedó sólo `0.022418` por delante del segundo, debajo del margen existente `0.05`.
- Las únicas omisiones fueron `_R4A4513.cr3` y `_R4A7192.cr3`, ambas de BAILARINA. Este caso queda como entrada medible del Módulo 4.

## Aislamiento y seguridad

- El selector admite exclusivamente referencias con extensión `.cr3`.
- CR2 y JPG no llaman conversión, Full RAW ni selección CR3.
- Preview y Full RAW conservan embeddings separados; el reporte no exporta ninguno.
- La fotografía y el código raíz no se sustituyen. El ancla operativa es evidencia interna.
- Una cara con confianza `0` no puede ser ancla.
- Las fotos grupales exigen correspondencia geométrica uno a uno y margen suficiente.
- Si la evidencia es insuficiente, el flujo anterior se conserva sin forzar una identidad.
- Full RAW queda acotado a 30 candidatos por rostro de referencia más las raíces; una prueba de 101 CR3 procesó sólo 31 en esta etapa.

## Reproducibilidad

Las corridas limpias 3, 4 y 5 produjeron el mismo resultado semántico:

- 21 correctas de 23.
- 21 entregadas.
- Precisión 100%.
- Ancla `_R4A1244.cr3`.
- Omisiones `_R4A4513.cr3` y `_R4A7192.cr3`.

El sidecar PyInstaller reconstruido reprodujo el mismo `21/23`, con precisión `100%` y cobertura `91.3%`. Su SHA-256 es `9FC3E0BB0EF30E3319EB63A2BE0D3AB4BF6506EBACCF6965EE561CDA085F1ED4`, idéntico al recurso sincronizado de Tauri.

La regresión dorada CR2 fue aprobada desde ese mismo ejecutable con la firma exacta de 259 asignaciones. También aprobaron 98/98 pruebas Python, la compilación de producción Vite y `cargo check --release`.

Evidencia final:

- `.codex_tmp/module3_cr3_20260811/natural_run_5/MODULE_3_CR3_NATURAL_EVALUATION.json`
- `.codex_tmp/module3_cr3_20260811/natural_run_5/resultado/_reporte_facesync.json`
- `.codex_tmp/module3_cr3_20260811/natural_run_5/resultado/_reporte_facesync.txt`
- `.codex_tmp/module3_cr3_20260811/natural_run_5/resultado/_reporte_facesync.xlsx`
- `.codex_tmp/module3_cr3_20260811/sidecar_run_1/MODULE_3_CR3_SIDECAR_EVALUATION.json`
- `.codex_tmp/module3_cr3_20260811/cr2_regression_final/output/_reporte_facesync.json`
