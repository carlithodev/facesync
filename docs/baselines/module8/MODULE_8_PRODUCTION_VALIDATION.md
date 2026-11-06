# Módulo 8: validación integral, regresión y empaquetado

## Veredicto

La **cadena técnica de producción queda aprobada**: código, sidecar PyInstaller, recursos Tauri, aplicación release, instalador NSIS e instalación limpia reprodujeron los resultados disponibles. CR2/JPG conservó exactamente su línea dorada y CR3 mantuvo `23/23` objetivos correctos con `12/12` controles rechazados en el conjunto real disponible.

El Módulo 8, sin embargo, queda **BLOQUEADO POR DATOS** y no se declara paridad CR3 general. No existen todavía los conjuntos reales exigidos por el plan para el Nivel 2 —mínimo cinco identidades repetidas— ni para el Nivel 3 —un salón CR3 de 15 a 30 alumnos con grupos y acompañantes—. El Nivel 4 tiene cobertura automatizada, pero no un lote real CR3 de tres salones con códigos reutilizados.

No se encontró una falla de código y no se modificó código productivo durante este módulo.

## Matriz de niveles

| Nivel | Estado | Evidencia | Límite |
|---|---|---|---|
| 1. Conjunto actual | **APROBADO** | 35 CR3 procesados: 23/23 objetivos correctos, 12/12 controles rechazados, cero errores RAW/imagen | Sólo dos identidades repetidas |
| 2. Diversidad mínima | **NO DISPONIBLE** | Hay dos identidades repetidas; las personas inéditas aparecen una sola vez | Faltan al menos tres identidades repetidas y poses variadas |
| 3. Salón representativo | **NO DISPONIBLE** | No existe un lote CR3 etiquetado de 15–30 alumnos | Faltan retratos, grupos, acompañantes y variación de luz de un salón real |
| 4. Códigos repetidos | **NO DISPONIBLE en datos reales** | Las pruebas automatizadas cubren segundo/tercer salón, reapertura, aislamiento por cuenta y descarte de propietarios previos | Falta repetirlo con tres salones CR3 reales |
| 5. Formatos mezclados | **APROBADO** | 1,841 imágenes JPG/CR2/CR3, 282 entregas, firma CR2 exacta y 23/23 CR3 | La diversidad CR3 sigue limitada a dos identidades |
| 6. Volumen | **APROBADO como prueba técnica** | 1,000 CR3 sin caché y con caché; salidas idénticas, cero errores y reportes completos | El lote usa enlaces duros y mide escala/estabilidad, no diversidad facial |

## Nivel 1: conjunto real disponible

Se procesaron los 31 CR3 originales y cuatro CR3 inéditos:

- 35/35 archivos analizados.
- 23/23 fotografías humanas objetivo correctas.
- 20/20 de ATLETA.
- 3/3 de BAILARINA.
- Precisión observada: 100%.
- Cobertura observada: 100%.
- 12/12 controles rechazados.
- Cero duplicados.
- Cero entregas desconocidas.
- Cero errores RAW.
- Cero errores de imagen.

Este resultado fue reproducido por el sidecar reconstruido y por el motor extraído de la instalación limpia.

## Nivel 4: cobertura automatizada disponible

Las pruebas automatizadas aprobaron los siguientes comportamientos:

- El mismo código CR3 puede existir en segundo y tercer salón por ruta.
- En el tercer salón se descartan ambos propietarios anteriores antes de seleccionar la identidad nueva.
- Preview y Full RAW permanecen separados por representación y versión.
- La limpieza del caché de embeddings no elimina el historial de identidades.
- Cerrar y volver a abrir la sesión conserva el registro.
- Las cuentas de usuario no comparten caché ni identidades.

Estas pruebas demuestran la lógica y persistencia, pero no sustituyen la prueba real solicitada con tres salones CR3.

## Nivel 5: mezcla JPG, CR2 y CR3

La ejecución mixta usó el lote dorado JPG/CR2 y el conjunto CR3 en dos carpetas de origen:

- 1,841 imágenes analizadas.
- 24 personas y 24 referencias encontradas.
- 282 archivos entregados.
- 259 asignaciones JPG/CR2 exactas.
- Firma JPG/CR2: `471F9281458F5A3A28F49FE1243757C44F8AA8750CB1E4E7EAC6594A4F8C30EE`.
- 23/23 CR3 correctos y originales entregados.
- Cero errores RAW.
- JSON, TXT y XLSX presentes.
- Full RAW procesó únicamente CR3; no procesó CR2.

Artefacto: `.codex_tmp/module8_cr3_20260811/mixed_sidecar_1/MODULE_8_MIXED_SIDECAR.json`.

## Nivel 6: volumen y caché

El lote técnico contiene 1,000 rutas CR3 mediante enlaces duros: una referencia humana válida y 999 controles sin persona. Sirve para medir volumen, memoria, estabilidad y reutilización; no mide reconocimiento de 1,000 fotografías facialmente distintas.

| Métrica | Caché fría | Caché caliente |
|---|---:|---:|
| CR3 encontrados/analizados | 1,000/1,000 | 1,000/1,000 |
| Tiempo de pared | 804.594 s | 34.859 s |
| Memoria máxima | 1,371.3 MB | 748.3 MB |
| Aciertos de caché de embeddings | 0% | 100% |
| Errores RAW | 0 | 0 |
| Errores de imagen | 0 | 0 |
| Reportes JSON/TXT/XLSX | Sí | Sí |

- Aceleración observada de caché caliente: `23.0814x`.
- Las asignaciones fría/caliente fueron idénticas.
- Firma de salida en ambas ejecuciones: `0ABD2799E604B456E9441B058413867F352860E95348548404366144B8E70090`.
- Full RAW procesó 1,000/1,000 CR3 en ambas ejecuciones sin errores.

Artefacto: `.codex_tmp/module8_cr3_20260811/volume_run_v1/MODULE_8_CR3_VOLUME.json`.

## Regresión obligatoria

| Comprobación | Estado | Resultado |
|---|---|---|
| Todas las pruebas automatizadas | **APROBADO** | 129/129 |
| Compilación Python | **APROBADO** | `compileall` sin errores |
| Lote dorado CR2 desde sidecar | **APROBADO** | 259 asignaciones exactas |
| Lote dorado CR2 desde instalación | **APROBADO** | 259 asignaciones: 130 CR2 + 129 JPG |
| Comparación antes/después CR2 | **APROBADO** | Firma exacta preservada |
| Full RAW CR3 excluido de CR2 | **APROBADO** | `fullraw_processed: 0` en CR2 |
| Cachés separados | **APROBADO** | Pruebas unitarias y métricas separadas CR2/CR3 |
| Compilación Vite | **APROBADO** | Build de producción |
| `cargo check --release` | **APROBADO** | Perfil optimizado |
| PyInstaller | **APROBADO** | Sidecar reconstruido |
| Sincronización Tauri | **APROBADO** | Hash del motor idéntico en origen/recurso/instalación |
| Instalador NSIS | **APROBADO** | Bundle generado con código 0 |
| Instalación desde cero | **APROBADO** | Instalación aislada en carpeta nueva; código 0 |
| Arranque de aplicación instalada | **APROBADO** | Ventana `FaceSync`, proceso respondiendo |
| Clasificación con motor instalado | **APROBADO** | CR3 y CR2 reproducidos desde el recurso instalado |
| Reportes y carpetas | **APROBADO** | JSON/TXT/XLSX presentes, XLSX legible y sin errores de fórmula |

## Protección de CR2/JPG

La regresión instalada procesó el lote real de 1,810 archivos:

- 22/22 referencias encontradas.
- 259 archivos entregados.
- 130 CR2.
- 129 JPG.
- Firma exacta `471F9281458F5A3A28F49FE1243757C44F8AA8750CB1E4E7EAC6594A4F8C30EE`.
- Cero errores de imagen.
- Cero errores DeepFace.
- Full RAW CR3 desactivado para CR2: `0` procesados.
- JSON, TXT y XLSX presentes.

Reporte instalado: `.codex_tmp/module8_cr3_20260811/installed_sidecar_cr2/output/_reporte_facesync.json`.

## Empaquetado e instalación

- Sidecar PyInstaller SHA-256: `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Recurso Tauri SHA-256: `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Motor instalado SHA-256: `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Instalador: `frontend/src-tauri/target/release/bundle/nsis/FaceSync_1.0.0_x64-setup.exe`.
- Tamaño del instalador: 739,126,475 bytes.
- Instalador SHA-256: `5166D1C89FC8ADA831A9622BE55AB285AA29DF1AA55218E10C500DD26997B54E`.
- Archivos instalados: 2,182.
- Tamaño instalado: 2,921.8 MB.
- La instalación previa y sus datos de sesión/caché no fueron modificados.

La interfaz instalada se abrió y respondió. La clasificación automatizada se ejecutó directamente contra el sidecar contenido en esa instalación, que es el recurso invocado por Tauri. No se automatizó el clic de la interfaz gráfica.

## Revisión de reportes instalados

La ejecución CR3 instalada produjo:

- 35 archivos encontrados y analizados.
- 2/2 referencias encontradas.
- 23 CR3 entregados.
- 12 controles ignorados.
- Cero errores.
- 21 hojas de auditoría en el XLSX.
- Cero errores de fórmula en el XLSX.
- Hojas `Fotos por persona` y `Selector referencia CR3` con los 23 registros y las dos identidades esperadas.

Reporte instalado: `.codex_tmp/module8_cr3_20260811/installed_sidecar_cr3/resultado/_reporte_facesync.json`.

## Versiones congeladas

- DeepFace: `0.0.100`.
- RetinaFace: `0.0.17`.
- TensorFlow: `2.21.0`.
- TF-Keras: `2.21.0`.
- ONNX Runtime DirectML: `1.24.4`.
- ArcFace SHA-256: `6336979C0C602CAE08D1122A66F4DFB862D059BBCD8EF80306AEF2B2249B0C93`.
- RetinaFace SHA-256: `ECB2393A89DA3DD3D6796AD86660E298F62A0C8AE7578D92EB6AF14E0BB93ADF`.

## Criterios finales todavía abiertos

No se pueden comprobar aún, con evidencia real comparable:

1. Precisión CR3 igual o superior a CR2 sobre cinco o más identidades repetidas.
2. Cobertura CR3 a no más de dos puntos porcentuales de CR2 sobre el mismo conjunto.
3. Fotografías grupales reales CR3 de un salón completo manejadas por rostro.
4. Códigos raíz reutilizados entre tres salones CR3 reales.

No se utiliza el 100% de la muestra actual para convertir esos cuatro puntos en una afirmación general.

## Datos mínimos para desbloquear y cerrar

Se necesitan tres pruebas, sin cambios de motor:

1. Un lote CR3 etiquetado de al menos cinco personas, con varias fotografías por persona, referencia natural, pose lateral y rostro pequeño.
2. Un salón CR3 de 15–30 alumnos con retratos, grupos, acompañantes y variación de luz.
3. Tres salones CR3 ejecutados en orden, reutilizando intencionalmente al menos un código raíz para personas diferentes y conservando el registro histórico.

Al recibir esos datos se reanuda únicamente la validación de los Niveles 2, 3 y 4. No existe justificación para cambiar el motor antes de observar un fallo reproducible.

## Condición de cierre

Módulo 8 **BLOQUEADO POR DATOS**:

- La cadena técnica de producción está aprobada.
- CR2/JPG permanece intacto.
- CR3 aprueba todos los conjuntos disponibles.
- El instalador y la instalación limpia funcionan.
- Faltan los conjuntos reales obligatorios de diversidad, salón y repetición entre tres salones.
- No se declara todavía paridad CR3 general ni cierre comercial definitivo de CR3.
