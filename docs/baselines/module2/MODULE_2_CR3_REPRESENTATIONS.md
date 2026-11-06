# Módulo 2 — Diagnóstico de representaciones CR3

## Alcance

- Fotografías medidas: `31`.
- Modelo: `ArcFace`.
- Detector: `retinaface`.
- Umbral observado, sin modificar: `0.28`.
- Los embeddings permanecieron en memoria y no forman parte de los artefactos.

## Distribuciones dentro de cada representación

Las parejas de la misma persona, personas diferentes y controles sin persona se reportan por separado.

| Ruta | Clase | N | Mín. | Mediana | P90 | Máx. | Media |
|---|---|---:|---:|---:|---:|---:|---:|
| preview | Misma persona | 191 | 0.0485 | 0.2826 | 0.8211 | 0.9562 | 0.3814 |
| preview | Personas diferentes | 40 | 0.2075 | 0.9029 | 1.0020 | 1.0308 | 0.8891 |
| preview | Control sin persona | 204 | 0.0068 | 0.8852 | 0.9459 | 1.0256 | 0.7749 |

- `preview`: AUC diagnóstica `0.9309`; aceptación de pares verdaderos a 0.28 `48.2%`; aceptación de pares humanos diferentes `2.5%`; pares excluidos por respaldo sin detección `30`.

| fullraw | Misma persona | 193 | 0.0355 | 0.2848 | 0.5016 | 0.7090 | 0.3009 |
| fullraw | Personas diferentes | 60 | 0.3500 | 0.9049 | 1.0091 | 1.0439 | 0.8977 |
| fullraw | Control sin persona | 212 | 0.0197 | 0.8755 | 0.9874 | 1.0298 | 0.7951 |

- `fullraw`: AUC diagnóstica `0.9891`; aceptación de pares verdaderos a 0.28 `47.2%`; aceptación de pares humanos diferentes `0.0%`; pares excluidos por respaldo sin detección `0`.

### Pares de personas distintas más cercanos

Esta tabla permite localizar solapamientos reales entre identidades humanas; los controles sin persona no se incluyen.

| Ruta | Foto A | Foto B | Distancia | Dentro de 0.28 |
|---|---|---|---:|---|
| preview | `_R4A1272.cr3` (ATLETA) | `_R4A7192.cr3` (BAILARINA) | 0.2075 | sí |
| preview | `_R4A1272.cr3` (ATLETA) | `_R4A6176.cr3` (BAILARINA) | 0.6886 | no |
| preview | `_R4A6176.cr3` (BAILARINA) | `_R4A9874.cr3` (ATLETA) | 0.7770 | no |
| fullraw | `_R4A0195.cr3` (ATLETA) | `_R4A4513.cr3` (BAILARINA) | 0.3500 | no |
| fullraw | `_R4A0195.cr3` (ATLETA) | `_R4A7192.cr3` (BAILARINA) | 0.3876 | no |
| fullraw | `_R4A0195.cr3` (ATLETA) | `_R4A6176.cr3` (BAILARINA) | 0.6130 | no |
## Correspondencia preview contra Full RAW

- Fotografías correspondientes: `31`.
- Distancia mediana entre representaciones: `0.0979`.
- Distancia P90 entre representaciones: `0.4612`.
- IoU mediana de caja facial: `0.9460`.
- Desplazamiento mediano del centro facial: `0.0032`.
- Cambios de orientación de imagen: `2`.
- Respaldos sin rostro detectado en preview: `1`.
- Respaldos sin rostro detectado en Full RAW: `0`.

### Fotografías con mayor cambio entre rutas

| Foto | Verdad | Distancia cruzada | IoU caja | Detección P/F | Preferencia por galería |
|---|---|---:|---:|---|---|
| `_R4A1272.cr3` | ATLETA | 0.9181 | 0.9323 | sí/sí | fullraw |
| `_R4A0055.cr3` | ATLETA | 0.7523 | 0.8034 | sí/sí | fullraw |
| `IMG_0226.CR3` | SIN OBJETIVO | 0.6008 | 0.8080 | sí/sí | insufficient_data |
| `IMG_0225.CR3` | SIN OBJETIVO | 0.4612 | 0.8233 | sí/sí | insufficient_data |
| `_R4A0195.cr3` | ATLETA | 0.4231 | 0.9493 | sí/sí | preview |
| `_R4A1229.cr3` | ATLETA | 0.4019 | 0.9643 | sí/sí | fullraw |
| `IMG_0224.CR3` | SIN OBJETIVO | 0.2322 | 0.8635 | sí/sí | insufficient_data |
| `_R4A0215.cr3` | ATLETA | 0.1854 | 0.9840 | sí/sí | preview |
| `_R4A0189.cr3` | ATLETA | 0.1714 | 0.9430 | sí/sí | preview |
| `IMG_0223.CR3` | SIN OBJETIVO | 0.1693 | 0.8708 | sí/sí | insufficient_data |
| `_R4A0229.cr3` | ATLETA | 0.1524 | 0.9696 | sí/sí | preview |
| `_R4A1235.cr3` | ATLETA | 0.1347 | 0.9349 | sí/sí | fullraw |

### Cambios de orientación o caja facial

| Foto | Preview | Full RAW | IoU caja | Desplazamiento centro | Observación |
|---|---|---|---:|---:|---|
| `_R4A0055.cr3` | horizontal | vertical | 0.8034 | 0.0054 | orientación distinta con rostro detectado |
| `_R4A4513.cr3` | horizontal | vertical | 0.0029 | 0.2224 | preview usó respaldo de imagen completa |

## Sensibilidad a postura, iluminación y tamaño facial

| Ruta | Corr. luz/distancia | Corr. tamaño/distancia | Misma postura N/mediana | Postura distinta N/mediana | Exposición extrema N/mediana |
|---|---:|---:|---:|---:|---:|
| preview | 0.4655 | 0.1810 | 190/0.2826 | 1/0.5747 | 37/0.8259 |
| fullraw | 0.2581 | 0.3836 | 191/0.2848 | 2/0.2671 | 37/0.2475 |

## Resultado por secuencia

La ruta preferida se determina por menor mediana de distancias internas verdaderas; no es una decisión de producción.

| Secuencia | Pares preview | Mediana preview | Pares Full RAW | Mediana Full RAW | Resultado |
|---|---:|---:|---:|---:|---|
| ATLETA_REFERENCIA_98 | 0 | N/A | 0 | N/A | insufficient_data |
| ATLETA_SERIE_00 | 55 | 0.1669 | 55 | 0.2482 | preview |
| ATLETA_SERIE_12 | 28 | 0.2507 | 28 | 0.1193 | fullraw |
| BAILARINA_SERIE | 1 | 0.5747 | 3 | 0.4606 | fullraw |
| CONTROL_MUNECA | 0 | N/A | 0 | N/A | insufficient_data |

## Diagnóstico de las omisiones

`reference_limited_but_identity_coherent` significa que la referencia natural queda fuera de 0.28, pero la fotografía sí forma un grupo coherente con otras imágenes reales de la misma persona.

| Ruta | Apoyo directo | Limitada por referencia | Difícil incluso con galería | Respaldo sin detección |
|---|---:|---:|---:|---:|
| preview | 2 | 17 | 3 | 1 |
| fullraw | 2 | 20 | 1 | 0 |

## Decisión documentada

- Estrategia: `independent_route_selection_by_sequence`.
- Ruta global seleccionada: `ninguna`.
- Motivo: Las secuencias no favorecen de forma uniforme a una sola representación; preview y Full RAW deben conservar espacios y decisiones independientes.
- Preview y Full RAW permanecen separados; sus embeddings no se mezclan ni se promedian.
- Este módulo no autoriza ajustes de umbral ni cambios en la clasificación.

## Limitaciones

- El conjunto contiene dos identidades humanas y ninguna fotografía grupal.
- Las etiquetas de postura son categorías de escena, no estimaciones biométricas de pose 3D.
- Los controles sin persona se reportan separados de las parejas de humanos distintos.
- Ninguna preferencia de ruta modifica parámetros o decisiones del clasificador.
