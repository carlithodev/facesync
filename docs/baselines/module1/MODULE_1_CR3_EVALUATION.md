# Módulo 1 — Medición facial y verdad de referencia CR3

## Conjunto etiquetado

- Fotografías CR3: `31`.
- Fotografías humanas objetivo: `23`.
- Fotografías sin identidad objetivo: `8`.
- Fotografías grupales: `0`.
- Fotografías con acompañantes humanos: `0`.

## Precisión y cobertura de las ejecuciones existentes

| Ejecución | Correctas | Entregadas originales | Reales | Precisión | Cobertura |
|---|---:|---:|---:|---:|---:|
| natural_references | 2 | 2 | 23 | 100.0% | 8.7% |
| favorable_control_reference | 18 | 18 | 23 | 100.0% | 78.3% |

### Resultado por identidad

#### natural_references

| Identidad | TP | FP | FN | Precisión | Cobertura |
|---|---:|---:|---:|---:|---:|
| ATLETA | 1 | 0 | 19 | 100.0% | 5.0% |
| BAILARINA | 1 | 0 | 2 | 100.0% | 33.3% |

Errores y omisiones exactos:

- `_R4A0055.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0142.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0149.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0156.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0160.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0170.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0177.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0189.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0195.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0215.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A0229.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1229.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1235.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1239.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1244.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1247.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1251.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1258.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1272.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A4513.cr3` — esperado: `BAILARINA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A7192.cr3` — esperado: `BAILARINA`; resultado: `omitida`; tipo: `false_negative`.

#### favorable_control_reference

| Identidad | TP | FP | FN | Precisión | Cobertura |
|---|---:|---:|---:|---:|---:|
| ATLETA | 17 | 0 | 3 | 100.0% | 85.0% |
| BAILARINA | 1 | 0 | 2 | 100.0% | 33.3% |

Errores y omisiones exactos:

- `_R4A0055.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A1229.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A4513.cr3` — esperado: `BAILARINA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A7192.cr3` — esperado: `BAILARINA`; resultado: `omitida`; tipo: `false_negative`.
- `_R4A9874.cr3` — esperado: `ATLETA`; resultado: `omitida`; tipo: `false_negative`.

Archivos auxiliares fuera del manifiesto:

- `_CONTROL9177.cr3` en `ATLETA`.

## Diagnóstico separado por representación

La predicción de esta sección usa solamente la referencia natural y el umbral directo `0.28`. No sustituye la ejecución real; sirve para explicar distancias y detectar dónde se rompe la cobertura.

| Ruta | Decodificadas | Con rostro | Rostros | Precisión directa | Cobertura directa |
|---|---:|---:|---:|---:|---:|
| preview | 31 | 31 | 31 | 100.0% | 8.7% |
| fullraw | 31 | 31 | 31 | 100.0% | 8.7% |

## Trazabilidad por fotografía

Cada fila muestra identidad real, cantidad de rostros, mejor distancia a referencia natural y la menor distancia a la galería de verdad leave-one-out. Las cajas completas, confianza, posición, distancias a ambas referencias y a cada identidad están en el JSON.

| Foto | Verdad | Preview: rostros / ref / galería | Full RAW: rostros / ref / galería |
|---|---|---|---|
| `_R4A0055.cr3` | ATLETA | 1 / 0.733356 / 0.680301 | 1 / 0.483536 / 0.245187 |
| `_R4A0142.cr3` | ATLETA | 1 / 0.452709 / 0.113341 | 1 / 0.437269 / 0.118257 |
| `_R4A0149.cr3` | ATLETA | 1 / 0.446294 / 0.056367 | 1 / 0.389879 / 0.058311 |
| `_R4A0156.cr3` | ATLETA | 1 / 0.439718 / 0.056367 | 1 / 0.416304 / 0.058311 |
| `_R4A0160.cr3` | ATLETA | 1 / 0.477806 / 0.069152 | 1 / 0.402043 / 0.068595 |
| `_R4A0170.cr3` | ATLETA | 1 / 0.462058 / 0.089603 | 1 / 0.452069 / 0.106619 |
| `_R4A0177.cr3` | ATLETA | 1 / 0.441372 / 0.108399 | 1 / 0.480397 / 0.128419 |
| `_R4A0189.cr3` | ATLETA | 1 / 0.512349 / 0.097288 | 1 / 0.500943 / 0.145165 |
| `_R4A0195.cr3` | ATLETA | 1 / 0.483675 / 0.149306 | 1 / 0.618627 / 0.375614 |
| `_R4A0215.cr3` | ATLETA | 1 / 0.496319 / 0.111306 | 1 / 0.460279 / 0.145165 |
| `_R4A0229.cr3` | ATLETA | 1 / 0.438239 / 0.133802 | 1 / 0.464768 / 0.256308 |
| `_R4A1229.cr3` | ATLETA | 1 / 0.621515 / 0.379 | 1 / 0.501603 / 0.155886 |
| `_R4A1235.cr3` | ATLETA | 1 / 0.557933 / 0.101395 | 1 / 0.543004 / 0.040895 |
| `_R4A1239.cr3` | ATLETA | 1 / 0.550399 / 0.048523 | 1 / 0.496492 / 0.03951 |
| `_R4A1244.cr3` | ATLETA | 1 / 0.512151 / 0.048523 | 1 / 0.501371 / 0.035529 |
| `_R4A1247.cr3` | ATLETA | 1 / 0.501384 / 0.067933 | 1 / 0.517017 / 0.05359 |
| `_R4A1251.cr3` | ATLETA | 1 / 0.498708 / 0.129213 | 1 / 0.47778 / 0.07162 |
| `_R4A1258.cr3` | ATLETA | 1 / 0.537021 / 0.17698 | 1 / 0.484835 / 0.091729 |
| `_R4A1272.cr3` | ATLETA | 1 / 0.881202 / 0.825865 | 1 / 0.510522 / 0.035529 |
| `_R4A4513.cr3` | BAILARINA | 1 / 0.713497 / 0.186165 | 1 / 0.519529 / 0.073525 |
| `_R4A6176.cr3` | BAILARINA | 1 / 0.0 / 0.574722 | 1 / 0.0 / 0.460609 |
| `_R4A7192.cr3` | BAILARINA | 1 / 0.574722 / 0.186165 | 1 / 0.460609 / 0.073525 |
| `_R4A9874.cr3` | ATLETA | 1 / 0.0 / 0.438239 | 1 / 0.0 / 0.389879 |
| `IMG_0219.CR3` | SIN OBJETIVO | 1 / N/A / 0.83821 | 1 / N/A / 0.825291 |
| `IMG_0220.CR3` | SIN OBJETIVO | 1 / N/A / 0.831753 | 1 / N/A / 0.826021 |
| `IMG_0221.CR3` | SIN OBJETIVO | 1 / N/A / 0.824596 | 1 / N/A / 0.813719 |
| `IMG_0222.CR3` | SIN OBJETIVO | 1 / N/A / 0.816438 | 1 / N/A / 0.756771 |
| `IMG_0223.CR3` | SIN OBJETIVO | 1 / N/A / 0.814258 | 1 / N/A / 0.681309 |
| `IMG_0224.CR3` | SIN OBJETIVO | 1 / N/A / 0.791437 | 1 / N/A / 0.547601 |
| `IMG_0225.CR3` | SIN OBJETIVO | 1 / N/A / 0.761364 | 1 / N/A / 0.188812 |
| `IMG_0226.CR3` | SIN OBJETIVO | 1 / N/A / 0.606361 | 1 / N/A / 0.02694 |

## Interpretación permitida

- Los resultados de clasificación se calculan desde las carpetas/reportes reales contra el manifiesto.
- Las rutas preview y Full RAW se miden por separado y sus embeddings no se combinan.
- La galería leave-one-out es diagnóstico de cohesión potencial, no una simulación de la galería de producción.
- El JSON no guarda embeddings; conserva únicamente medidas y distancias necesarias para reproducir conclusiones.
- Este módulo mide y explica. No cambia umbrales ni decisiones del clasificador.
