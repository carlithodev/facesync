# Módulo 7: calibración CR3 basada en datos

## Veredicto

El módulo queda **completado como calibración `no-op`**: la evidencia disponible no justifica cambiar ningún parámetro exclusivo de CR3. La configuración de entrada ya entregó las `23/23` fotografías humanas correctas, mantuvo precisión y cobertura de `100%`, rechazó las `12/12` fotografías sin identidad objetivo y procesó `35/35` archivos CR3 sin errores.

Modificar límites con sólo dos identidades repetidas habría reducido seguridad y sobreajustado el motor. Por ello, el resultado correcto de la calibración fue conservar exactamente la configuración aprobada en los Módulos 3 a 6.

## Límites respetados

No se modificaron:

- RetinaFace.
- ArcFace.
- Los umbrales generales `0.28` y `0.40`.
- Las reglas JPG/CR2.
- La selección de referencia CR3 del Módulo 3.
- El arranque de galería CR3 del Módulo 4.
- El árbitro preview/Full RAW del Módulo 5.
- El historial SQLite por ruta del Módulo 6.

No hubo cambios en código productivo. Sólo se añadió una utilidad diagnóstica de pruebas para construir hojas visuales de previews CR3.

## Inventario real

El conjunto principal contiene `31` CR3:

- `23` fotografías humanas objetivo.
- `20` fotografías de ATLETA.
- `3` fotografías de BAILARINA.
- `8` controles sin persona real.

La carpeta descargada `CanonR3samples-220323-190954` no añadió evidencia independiente: sus `23` CR3 reales son copias byte por byte de los archivos Canon ya presentes en el conjunto principal. Los `13` archivos adicionales con prefijo `.__` son metadatos de macOS de `220` bytes, no fotografías CR3 válidas.

Se localizaron cuatro CR3 realmente nuevos:

| Archivo | Contenido visible | Uso en M7 |
|---|---|---|
| `canon_eos_m50_02.cr3` | Dos personas desconocidas | Control humano negativo |
| `IMG_0163.CR3` | Paisaje | Control sin persona |
| `IMG_0482_raw.CR3` | Paisaje urbano | Control sin persona |
| `IMG_0483_craw.CR3` | Misma escena urbana con otra codificación RAW | Control sin persona |

La fotografía con dos desconocidos aporta dos identidades inéditas, pero sólo una observación por persona. Sirve para medir falsos positivos frente a ATLETA y BAILARINA; no permite medir cobertura ni formar una pareja verdadera independiente.

## Distribuciones actuales por representación

Estas distribuciones proceden del diagnóstico etiquetado del Módulo 2 y son la medición disponible antes de decidir cualquier ajuste. Menor distancia significa mayor similitud.

| Ruta | Clase | Pares | Mínimo | Mediana | P90 | Máximo | AUC | Aceptación a 0.28 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Preview | Misma identidad | 191 | 0.048523 | 0.282580 | 0.821052 | 0.956203 | 0.930890 | 48.17% |
| Preview | Identidades distintas | 40 | 0.207546 | 0.902886 | 1.001985 | 1.030798 | — | 2.50% |
| Full RAW | Misma identidad | 193 | 0.035529 | 0.284807 | 0.501557 | 0.709017 | 0.989119 | 47.15% |
| Full RAW | Identidades distintas | 60 | 0.350040 | 0.904890 | 1.009136 | 1.043933 | — | 0.00% |

La distancia individual no separa por sí sola todos los casos preview. El resultado final `23/23` se obtiene por la combinación ya aprobada de referencia recurrente, grupos coherentes, margen entre identidades, rutas separadas y arbitraje por rostro. Esta evidencia descarta ampliar umbrales directos.

## Parámetros evaluados y decisión

| Parámetro | Valor conservado | Decisión |
|---|---:|---|
| Soportes mínimos independientes | `2` | Conservar; una sola foto no puede enseñar una identidad |
| Margen de referencia frente a otra identidad | `0.05` | Conservar; no hubo falsos negativos finales que justificaran relajarlo |
| Margen de galería en el árbitro | `0.04` | Conservar; bloquea decisiones cercanas sin afectar el lote real |
| Coherencia/vecindad de referencia | `0.40` | Conservar; recuperó secuencias difíciles sin entregas ajenas |
| IoU mínimo entre rutas | `0.25` | Conservar; relaciona rostros por geometría sin mezclar embeddings |
| Margen geométrico | `0.05` en arbitraje | Conservar; la prueba ampliada no mostró conflictos |
| Alimentadores CR3 por identidad | `15` | Conservar; no se observó insuficiencia de cobertura |
| Límite de candidatos de arranque | `30` | Conservar; mantiene la búsqueda acotada |
| Consenso preview/Full RAW | Decisión por rostro; preview segura inmutable | Conservar; `5` rescates Full RAW y `0` errores finales |

Los umbrales generales `0.28/0.40` aparecen únicamente como límites heredados y congelados; no fueron candidatos a modificación.

## Antes y después

| Métrica | Antes de M7 | Después de M7 |
|---|---:|---:|
| Parámetros productivos cambiados | 0 | 0 |
| Fotografías objetivo correctas | 23/23 | 23/23 |
| Precisión observada | 100% | 100% |
| Cobertura observada | 100% | 100% |
| Falsos positivos | 0 | 0 |
| Falsos negativos | 0 | 0 |
| Errores RAW/imagen | 0 | 0 |

No existe una variante “después” distinta: ésa es precisamente la conclusión de la calibración. La configuración actual es la candidata seleccionada.

## Validación ampliada desde código fuente

Se procesaron las `31` muestras originales y los cuatro CR3 inéditos en una carpeta aislada y con datos de aplicación limpios.

- CR3 analizados: `35`.
- Fotografías objetivo correctas: `23/23`.
- Precisión: `100%`.
- Cobertura: `100%`.
- Controles rechazados: `12/12`.
- Nuevas fotografías rechazadas correctamente: `4/4`.
- Personas desconocidas entregadas a una identidad existente: `0`.
- Duplicados: `0`.
- Entregas desconocidas: `0`.
- Errores RAW: `0`.
- Errores de imagen: `0`.

Artefacto: `.codex_tmp/module7_cr3_20260811/classification_unseen_negatives_1/MODULE_3_CR3_NATURAL_EVALUATION.json`.

## Validación desde el sidecar empaquetado

La misma prueba ampliada se repitió desde `engine/dist/FaceSyncEngine/FaceSyncEngine.exe`.

- SHA-256 del sidecar: `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- CR3 analizados: `35`.
- Fotografías objetivo correctas: `23/23`.
- Precisión: `100%`.
- Cobertura: `100%`.
- Nuevas fotografías rechazadas correctamente: `4/4`.
- Errores RAW: `0`.
- Errores de imagen: `0`.

Artefacto: `.codex_tmp/module7_cr3_20260811/sidecar_unseen_negatives_1/MODULE_3_CR3_SIDECAR_EVALUATION.json`.

## Protección de CR2/JPG y compilación

- Regresión dorada CR2 desde sidecar: **APROBADA**.
- Asignaciones CR2/JPG: `259`, con firma exacta preservada.
- Pruebas automatizadas: `129/129` aprobadas.
- Compilación Python: aprobada.
- Compilación Vite: aprobada.
- `cargo check --release`: aprobado.

Reporte CR2: `.codex_tmp/module7_cr3_20260811/cr2_golden_regression/output/_reporte_facesync.json`.

## Alcance de la conclusión

La calibración disponible confirma que no hay un ajuste seguro ni necesario que realizar con los datos actuales. La precisión observada de CR3 iguala la de la referencia CR2 y la diferencia de cobertura observada es de `0` puntos porcentuales en los conjuntos comprobados.

Esto no convierte a las cuatro fotografías nuevas en una validación positiva de identidades inéditas: no existe una segunda fotografía de esas personas para medir reconocimiento. La validación comercial general con más personas, grupos y cámaras corresponde al Módulo 8 y no fue iniciada.

## Condición de cierre

Módulo 7 **COMPLETADO**:

- Se midió la configuración actual.
- Se revisaron distribuciones verdaderas y falsas por ruta.
- Se separó la evidencia nueva utilizable como control negativo.
- Se descartaron cambios no respaldados por datos.
- La configuración elegida aprobó código fuente, sidecar y regresión CR2 exacta.
- Se documentó explícitamente la limitación de identidades inéditas repetidas.
