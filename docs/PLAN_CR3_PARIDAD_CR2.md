# Plan maestro: paridad de reconocimiento CR3 con CR2

## 1. Propósito del documento

Este documento es la fuente única de verdad para el trabajo relacionado con el reconocimiento facial de archivos `.CR3` en FaceSync.

Sus objetivos son:

- Mantener el trabajo ordenado por módulos.
- Evitar repetir pruebas o implementar dos veces la misma solución.
- Impedir cambios aislados, improvisados o sin medición.
- Proteger completamente el funcionamiento validado de `.CR2`.
- Documentar qué se hizo, qué falta, qué se comprobó y por qué se tomó cada decisión.
- Alcanzar en `.CR3` una efectividad comparable con la obtenida en `.CR2`.

Ningún módulo debe comenzar hasta que el módulo anterior cumpla su condición de cierre. Si una prueba falla, se permanece en el módulo actual hasta comprender y resolver la causa.

---

## 2. Meta principal

Conseguir que FaceSync clasifique fotografías `.CR3` con una precisión y cobertura comparables a `.CR2`, sin alterar:

- El flujo validado de `.CR2`.
- RetinaFace.
- ArcFace.
- Los umbrales generales del motor.
- Las reglas de asignación ya aprobadas.
- Las auditorías de referencias y códigos repetidos.
- El funcionamiento actual de JPG y CR2.

La paridad se evaluará con datos medibles. No se declarará por intuición, por una sola prueba favorable ni por el simple hecho de que el formato pueda abrirse.

---

## 3. Límites no negociables

1. La ruta validada de `.CR2` queda congelada.
2. No se modificarán ArcFace ni RetinaFace.
3. No se cambiarán al azar los umbrales generales:
   - Coincidencia segura: `0.28`.
   - Zona de revisión: `0.40`.
4. No se mezclarán ni promediarán embeddings del preview y del Full RAW.
5. Las dos representaciones CR3 deberán permanecer identificadas y separadas.
6. Todo cambio será exclusivo de la adaptación o recuperación CR3, salvo pruebas y reportes compartidos que no alteren decisiones.
7. Cada modificación deberá incluir una prueba que demuestre su comportamiento.
8. Después de cada módulo se ejecutará la regresión de CR2.
9. No se avanzará al siguiente módulo si el actual no cumple su condición de cierre.
10. No se reconstruirá el instalador final hasta aprobar las pruebas de código y del ejecutable del módulo correspondiente.

---

## 4. Definiciones de medición

Para evitar confusiones, se usarán estas métricas:

### Precisión

Porcentaje de fotografías entregadas en una carpeta que realmente contienen al alumno correspondiente.

```text
precisión = asignaciones correctas / asignaciones realizadas
```

### Cobertura o recall

Porcentaje de las fotografías reales de un alumno que FaceSync consiguió recuperar.

```text
cobertura = fotografías correctas recuperadas / fotografías reales del alumno
```

### Falso positivo

Fotografía entregada a un alumno que no aparece en ella.

### Falso negativo u omisión

Fotografía que sí corresponde al alumno, pero no fue clasificada en su carpeta.

### Referencia natural

Fotografía seleccionada por el código raíz proveniente del Excel, sin reemplazarla manualmente por otra imagen más favorable.

### Preview CR3

JPEG embebido por la cámara dentro del archivo RAW y utilizado como primera representación.

### Full RAW CR3

Revelado del RAW mediante LibRaw/rawpy a media resolución y guardado en un caché independiente para una segunda evaluación.

### Paridad con CR2

Resultado CR3 que, bajo condiciones equivalentes, conserva la precisión de CR2 y queda como máximo a dos puntos porcentuales de su cobertura.

---

## 5. Estado confirmado antes de comenzar

Fecha de referencia: 10 de agosto de 2026.

### Componentes CR3 ya funcionales

- Escaneo de archivos `.CR3`.
- Lectura mediante `rawpy`.
- Extracción del preview embebido.
- Conversión de respaldo mediante Full RAW.
- Detección facial con RetinaFace.
- Generación de embeddings con ArcFace.
- Caché de conversiones.
- Caché persistente de embeddings.
- Caché Full RAW independiente.
- Separación de métricas CR2 y CR3.
- Galería dinámica en la ruta principal.
- Galería independiente en la segunda ruta Full RAW.
- Auditorías de referencias.
- Registro histórico por usuario mediante SQLite.
- Entrega de originales `.CR3`.
- Entrega de archivos gemelos JPG/CR2/CR3.
- Reportes JSON, TXT y XLSX con métricas CR3.
- Vista previa de archivos RAW.
- Inclusión del motor CR3 en el instalador actual.

### Evidencia automatizada actual

- Pruebas ejecutadas: `80`.
- Pruebas aprobadas: `80`.
- Fallos: `0`.

Estas pruebas confirman estructura, aislamiento, caché, entrega y reglas. No sustituyen la validación de efectividad facial con fotografías reales.

### Prueba CR3 con referencias naturales

Reporte:

`C:\Users\ianca\Desktop\FaceSyncV2\.codex_tmp\cr3_run_20260809_2\_reporte_facesync.json`

Resultados:

- Fotografías CR3 analizadas: `31`.
- Errores RAW: `0`.
- Errores de imagen: `0`.
- Fotografías entregadas: `2`.
- Fotografías no asignadas: `29`.
- Referencias sin apoyo visual: `2`.
- Rescates Full RAW: `0`.
- Tiempo total: `42.17 s`.

### Prueba CR3 con referencia de control favorable

Reporte:

`C:\Users\ianca\Desktop\FaceSyncV2\.codex_tmp\cr3_run_20260809_3\_reporte_facesync.json`

Resultados relevantes sobre las 23 fotografías originales de personas:

- Fotografías humanas correctamente clasificadas: `18 de 23`.
- Cobertura humana: `78.3%`.
- Persona principal: `17 de 20`, equivalente a `85%`.
- Segunda persona: `1 de 3`, equivalente a `33%`.
- Falsas asignaciones observadas: `0`.
- Fotografías del muñeco correctamente ignoradas: `8 de 8`.
- Rescates de la galería principal: `1`.
- Rescates exclusivos de Full RAW: `1`.
- Errores RAW: `0`.
- Errores de imagen: `0`.

La ejecución completa analizó `32` archivos porque incluyó una copia temporal utilizada como referencia de control. Esa copia no debe contarse como una fotografía humana original del conjunto.

### Diagnóstico A/B de representación

- Archivos abiertos correctamente: `31 de 31`.
- Rostros detectados: `31 de 31`.
- Embeddings preview y Full RAW prácticamente equivalentes: `6 de 31`.
- Fotografías con diferencias apreciables entre representaciones: `25 de 31`.

Conclusión inicial: CR3 es técnicamente estable, pero su reconocimiento presenta una dependencia excesiva de la referencia y una cobertura inferior a la comprobada en CR2.

---

## 6. Deficiencias confirmadas del reconocimiento CR3

### 6.1 Dependencia excesiva de la referencia

Una referencia favorable produjo una cobertura alta para la persona principal. La referencia natural indicada por el Excel no produjo fotografías de apoyo.

Esto demuestra que el formato ya se procesa, pero la identidad no se fortalece correctamente cuando la fotografía raíz cambia de pose, tamaño, encuadre o apariencia respecto al resto del lote.

### 6.2 Arranque en frío de la galería

La galería necesita coincidencias seguras para aprender nuevos ejemplos. Cuando la referencia no genera esas primeras coincidencias ocurre el siguiente ciclo:

1. No aparecen candidatos seguros.
2. La galería no recibe alimentadores.
3. La identidad no aprende otras poses.
4. Las fotografías verdaderas permanecen fuera.
5. El alumno termina únicamente con su referencia.

### 6.3 Diferencia entre preview y Full RAW

Ambas representaciones contienen la misma fotografía, pero pueden producir embeddings diferentes por revelado, orientación, escala, nitidez y procesamiento interno de la cámara.

Las representaciones no deben mezclarse como si fueran idénticas. Deben compararse y decidirse de forma independiente.

### 6.4 Full RAW participa demasiado tarde

La segunda ruta se ejecuta después de la decisión principal y solamente puede agregar identidades no aseguradas.

Actualmente no puede:

- Fortalecer la referencia antes de la primera clasificación.
- Construir una galería suficiente si la ruta principal comenzó sin apoyos.
- Replantear una referencia CR3 débil desde el inicio.

### 6.5 Riesgo de seleccionar otro rostro entre representaciones

En una fotografía grupal puede haber varios rostros. La diferencia entre embeddings preview y Full RAW puede dificultar identificar cuál rostro de una ruta corresponde al de la otra.

Este riesgo todavía no se manifestó como una mezcla en la muestra, pero debe quedar cubierto antes de aprobar fotografías grupales CR3.

### 6.6 Registro histórico no completamente consciente de la representación

El caché Full RAW está separado, pero los registros históricos confirmados se forman principalmente a partir del flujo base. Para blindar códigos repetidos en CR3 será necesario conservar el tipo y la versión de la representación utilizada por cada anclaje.

### 6.7 Validación real insuficiente

El conjunto actual contiene solamente dos personas reales. Es útil para diagnóstico, pero insuficiente para afirmar generalidad con muchos alumnos, grupos, cámaras, salones y condiciones fotográficas.

---

## 7. Arquitectura objetivo para CR3

El flujo objetivo será:

1. Leer el código raíz del Excel.
2. Localizar todas las fotografías candidatas con ese código.
3. Generar la representación preview de la referencia.
4. Generar la representación Full RAW de la referencia CR3.
5. Relacionar el mismo rostro entre ambas representaciones mediante geometría facial, no solamente por distancia de embedding.
6. Evaluar preview contra preview.
7. Evaluar Full RAW contra Full RAW.
8. Medir cuál ruta produce el grupo más coherente para esa identidad.
9. Construir una galería inicial con varios anclajes seguros.
10. Reprocesar candidatos débiles con la galería fortalecida.
11. Combinar decisiones de ambas rutas sin combinar sus embeddings.
12. Auditar contradicciones contra otras identidades.
13. Entregar únicamente una decisión visualmente respaldada.
14. Guardar anclajes confirmados con representación y versión.
15. Generar métricas que expliquen cada recuperación u omisión.

---

## 8. Ejecución por módulos

### Estado general

| Módulo | Nombre | Estado |
|---|---|---|
| 0 | Congelar y documentar la base | COMPLETADO |
| 1 | Medición facial y verdad de referencia | COMPLETADO |
| 2 | Diagnóstico de representaciones CR3 | COMPLETADO |
| 3 | Fortalecimiento de la referencia CR3 | COMPLETADO |
| 4 | Arranque seguro de la galería CR3 | COMPLETADO |
| 5 | Decisión coordinada preview/Full RAW | COMPLETADO |
| 6 | Registro histórico y caché consciente de ruta | COMPLETADO |
| 7 | Calibración CR3 basada en datos | COMPLETADO |
| 8 | Producción, regresión y empaquetado | BLOQUEADO |

Estados permitidos:

- `PENDIENTE`
- `EN PROCESO`
- `BLOQUEADO`
- `COMPLETADO`

Solo puede existir un módulo con estado `EN PROCESO`.

---

## Módulo 0: congelar y documentar la base

### Objetivo

Crear una línea base reproducible que permita comprobar que ningún trabajo CR3 modifica los resultados de CR2.

### Tareas

- [x] Registrar hashes del código y ejecutable inicial.
- [x] Conservar los reportes CR3 actuales.
- [x] Guardar las métricas iniciales descritas en este documento.
- [x] Ejecutar y registrar las 80 pruebas actuales.
- [x] Seleccionar un lote CR2 validado como prueba dorada.
- [x] Ejecutar el lote CR2 sin caché.
- [x] Guardar asignaciones, conteos, errores y reportes del lote CR2.
- [x] Definir el comando único de regresión.

### Entregables

- Registro de versión inicial.
- Resultado de las pruebas automatizadas.
- Reporte dorado CR2.
- Reportes base CR3.
- Tabla de métricas iniciales.

### Condición de cierre

Debe ser posible repetir el lote dorado CR2 y obtener los mismos resultados antes de comenzar modificaciones CR3.

---

## Módulo 1: medición facial y verdad de referencia

### Objetivo

Construir una medición precisa por rostro que permita saber por qué cada fotografía fue asignada, recuperada u omitida.

### Tareas

- [x] Crear un manifiesto de verdad de referencia para las imágenes actuales.
- [x] Etiquetar cada identidad real.
- [x] Etiquetar rostros acompañantes en fotografías grupales cuando existan.
- [x] Registrar fotografías sin identidad objetivo.
- [x] Calcular precisión y cobertura por persona.
- [x] Registrar falsos positivos y falsos negativos.
- [x] Registrar resultado de preview y Full RAW por separado.
- [x] Registrar tamaño, confianza y posición de cada rostro.
- [x] Registrar distancias a la referencia y a la galería.
- [x] Generar un reporte comparativo reproducible.

### Entregables

- Manifiesto etiquetado.
- Evaluador CR3.
- Reporte de precisión y cobertura por identidad.
- Lista exacta de errores y omisiones.

### Condición de cierre

Cada resultado debe poder explicarse mediante datos. No se admiten conclusiones basadas únicamente en revisar carpetas visualmente.

---

## Módulo 2: diagnóstico de las dos representaciones CR3

### Objetivo

Determinar qué representación ofrece mayor estabilidad y bajo qué condiciones.

### Tareas

- [x] Calcular distancias preview contra preview.
- [x] Calcular distancias Full RAW contra Full RAW.
- [x] Calcular preview contra Full RAW únicamente como diagnóstico.
- [x] Separar coincidencias de la misma persona y de personas diferentes.
- [x] Medir sensibilidad a postura, tamaño e iluminación.
- [x] Identificar qué fotografías cambian más entre rutas.
- [x] Identificar si la orientación o caja facial cambia entre rutas.
- [x] Determinar cuál ruta funciona mejor para cada secuencia.
- [x] Documentar distribuciones de distancias verdaderas y falsas.

### Entregables

- Matriz A/B por fotografía y rostro.
- Distribución de distancias por ruta.
- Diagnóstico de causas de las omisiones.
- Decisión documentada sobre la estrategia de representación.

### Condición de cierre

Se debe conocer con evidencia si conviene priorizar preview, Full RAW o decisiones independientes según calidad. No se modificará ningún parámetro sin este diagnóstico.

---

## Módulo 3: fortalecimiento de la referencia CR3

### Objetivo

Hacer que una referencia natural del Excel pueda representar a la identidad sin escoger manualmente una fotografía favorable.

### Diseño aislado autorizado

- El código del Excel y la ruta de la fotografía raíz permanecerán como autoridad; nunca se sustituirán ni se renombrarán.
- Preview y Full RAW formarán espacios de evidencia independientes y nunca compartirán ni promediarán embeddings.
- La relación de un rostro entre ambas rutas se resolverá por caja facial normalizada, orientación y correspondencia uno a uno. En fotografías grupales no se admitirá una relación geométricamente ambigua.
- Cada rostro candidato de la referencia medirá confianza, tamaño, recurrencia en fotografías distintas, coherencia interna y separación frente a las demás referencias.
- Solamente podrá promoverse un ancla operativa única cuando un grupo visual tenga soporte repetido y margen frente a otras identidades. Se prioriza una conexión directa dentro de los límites existentes; si no existe, la búsqueda más amplia sirve únicamente para comparar grupos coherentes y exige que el mejor supere claramente al segundo. Esa búsqueda no entrega fotografías por sí sola.
- La cara promovida deberá existir en las dos representaciones de la misma fotografía y conservará un embedding distinto por ruta.
- Si falta soporte, separación o correspondencia geométrica, el flujo CR3 conservará la referencia actual sin forzar una sustitución.
- Este módulo no construirá una galería de varios anclajes, no reabrirá fotografías omitidas y no cambiará umbrales; esas responsabilidades pertenecen a los Módulos 4, 5 y 7.

### Tareas

- [x] Crear candidato preview de la referencia.
- [x] Crear candidato Full RAW de la misma referencia.
- [x] Relacionar el mismo rostro entre rutas por geometría facial.
- [x] Medir calidad, tamaño y confianza del rostro.
- [x] Medir recurrencia en otras fotografías.
- [x] Medir separación respecto a otros alumnos.
- [x] Escoger la representación con el grupo visual más coherente.
- [x] Mantener el código del Excel como autoridad.
- [x] Proteger fotografías grupales con selección por rostro.
- [x] Agregar pruebas automatizadas para referencia lateral, pequeña y grupal.

### Entregables

- Selector de referencia CR3 por evidencia.
- Diagnóstico de selección incluido en el reporte.
- Pruebas unitarias de aislamiento respecto a CR2.
- Resultado con las referencias naturales del conjunto actual.

### Condición de cierre

Las referencias naturales deberán producir apoyo visual medible y superar claramente la clasificación base sin introducir falsas asignaciones.

---

## Módulo 4: arranque seguro de la galería CR3

### Objetivo

Permitir que una identidad forme una galería inicial aunque su referencia no produzca coincidencias directas ultra seguras.

### Problema exacto en proceso

La selección conservadora del Módulo 3 mantiene 100% de precisión, pero deja fuera `_R4A4513.cr3` y `_R4A7192.cr3`. Este módulo debe reunir evidencia CR3 de varias fotografías y formar anclajes independientes por ruta para volver a evaluar omisiones, sin convertir candidatos aislados o rostros acompañantes en alimentadores y sin alterar el flujo JPG/CR2.

### Tareas

- [x] Reunir los mejores candidatos de cada ruta sin entregarlos todavía.
- [x] Agrupar candidatos por similitud mutua.
- [x] Buscar un grupo coherente conectado con la referencia.
- [x] Verificar separación frente a todas las demás identidades.
- [x] Exigir múltiples evidencias antes de alimentar la galería.
- [x] Crear varios anclajes por identidad.
- [x] Volver a evaluar fotografías omitidas.
- [x] Impedir que un candidato aislado contamine la galería.
- [x] Impedir que un rostro acompañante se convierta en referencia.
- [x] Reportar cada alimentador y su evidencia.

### Reglas de seguridad

- Una búsqueda más amplia sirve para encontrar candidatos, no para asignarlos directamente.
- La decisión final necesita coherencia de grupo y margen frente a otras identidades.
- Un solo candidato débil no puede enseñar a la galería.
- Los anclajes deben provenir de fotografías distintas.

### Entregables

- Arranque de galería exclusivo de CR3.
- Registro de alimentadores y bloqueos.
- Pruebas de contaminación y de identidades parecidas.
- Nueva medición de cobertura y precisión.

### Condición de cierre

La cobertura debe aumentar con referencias débiles y la precisión no debe disminuir respecto a la línea base.

---

## Módulo 5: decisión coordinada preview y Full RAW

### Objetivo

Combinar evidencia de las dos representaciones sin mezclar embeddings ni reemplazar decisiones seguras.

### Reglas propuestas

1. Una coincidencia segura del flujo base se conserva.
2. Una fotografía no asignada puede recibir una segunda evaluación Full RAW.
3. Si ambas rutas coinciden, la identidad gana respaldo.
4. Si solamente Full RAW tiene evidencia segura y coherente, puede recuperar la fotografía.
5. Si las rutas proponen personas diferentes, se ejecuta una auditoría de contradicción.
6. Si no existe respaldo suficiente, no se fuerza una identidad incorrecta.
7. La decisión se hace por rostro, no solamente por archivo.

### Tareas

- [x] Crear estructura de decisión independiente por ruta.
- [x] Relacionar rostros entre representaciones.
- [x] Aplicar margen frente a otras identidades.
- [x] Aplicar consenso de galería.
- [x] Bloquear contradicciones entre rutas.
- [x] Mantener inmutables las asignaciones base seguras.
- [x] Registrar el motivo de cada rescate o bloqueo.
- [x] Probar fotografías grupales y múltiples identidades.

### Entregables

- Árbitro CR3 de decisiones por ruta.
- Reporte de coincidencias, desacuerdos y rescates.
- Pruebas de no reemplazo de decisiones seguras.
- Medición actualizada.

### Condición de cierre

La recuperación debe aumentar sin crear mezclas y sin cambiar ninguna asignación CR2 del lote dorado.

---

## Módulo 6: registro histórico y caché consciente de ruta

### Objetivo

Guardar referencias CR3 confirmadas de manera que puedan utilizarse con seguridad en códigos repetidos entre distintos salones.

### Datos que debe conservar cada registro CR3

- Código.
- Alumno.
- Salón.
- Excel.
- Carpetas de origen.
- Fotografía raíz.
- Hash de la referencia.
- Representación: preview o Full RAW.
- Versión de procesamiento.
- Embedding principal.
- Anclajes confirmados.
- Cantidad de soportes.
- Coherencia.
- Fecha de clasificación.
- Cámara, cuando esté disponible.

### Tareas

- [x] Revisar compatibilidad del esquema SQLite actual.
- [x] Diseñar migración aditiva si se necesita información de representación.
- [x] Versionar el caché CR3.
- [x] Mantener intacto el caché CR2.
- [x] Evitar comparar anclajes incompatibles sin conocer su ruta.
- [x] Registrar solamente identidades con múltiples soportes confirmados.
- [x] Probar el mismo código en segundo y tercer salón.
- [x] Probar cierre de sesión y separación entre usuarios.
- [x] Probar limpieza de caché sin eliminar el registro histórico.

### Entregables

- Registro histórico CR3 consciente de representación.
- Migración segura, si resulta necesaria.
- Pruebas de códigos repetidos entre salones.
- Pruebas de aislamiento por usuario.

### Condición de cierre

Un código repetido CR3 debe resolverse utilizando identidad histórica sin mezclar alumnos, formatos, salones ni usuarios.

---

## Módulo 7: calibración CR3 basada en datos

### Objetivo

Determinar si todavía es necesario ajustar parámetros exclusivos de recuperación CR3 después de corregir referencias y galerías.

### Orden obligatorio

1. Probar con los umbrales actuales.
2. Medir distribuciones verdaderas y falsas.
3. Separar datos de ajuste y de validación.
4. Ajustar solamente parámetros CR3 respaldados por evidencia.
5. Validar con personas que no participaron en el ajuste.
6. Comparar nuevamente con CR2.

### Parámetros que podrían evaluarse

- Calidad mínima de referencia CR3.
- Número mínimo de soportes de arranque.
- Margen entre identidades.
- Coherencia mínima del grupo.
- Radio de búsqueda de candidatos, sin convertirlo automáticamente en umbral de entrega.
- Reglas de consenso entre preview y Full RAW.
- Coincidencia geométrica entre caras de ambas rutas.

### Parámetros que no se modificarán

- Modelo ArcFace.
- Detector RetinaFace.
- Umbrales generales del flujo CR2.
- Reglas validadas de entrega CR2.

### Entregables

- Informe de calibración.
- Comparación antes y después.
- Parámetros CR3 documentados.
- Validación independiente.

### Condición de cierre

CR3 debe conservar la precisión de CR2 y quedar como máximo a dos puntos porcentuales de su cobertura en condiciones equivalentes.

---

## Módulo 8: producción, regresión y empaquetado

### Objetivo

Confirmar que la solución funciona en el código, en el motor empaquetado y desde la aplicación instalada.

### Niveles de prueba

#### Nivel 1: conjunto actual

- 31 fotografías originales CR3.
- Dos personas reales.
- Fotografías ajenas o del muñeco.
- Referencias naturales.

#### Nivel 2: diversidad mínima

- Mínimo 5 personas.
- Varias poses por persona.
- Referencias naturales.
- Rostros pequeños y laterales.

#### Nivel 3: salón representativo

- Entre 15 y 30 alumnos.
- Retratos y fotografías grupales.
- Personas acompañantes.
- Diferentes condiciones de luz.

#### Nivel 4: códigos repetidos

- Segundo salón.
- Tercer salón.
- Mismo código raíz para personas distintas.
- Registro histórico existente.

#### Nivel 5: formatos mezclados

- JPG.
- CR2.
- CR3.
- Archivos gemelos.
- Varias carpetas de origen.

#### Nivel 6: volumen

- Al menos 1,000 CR3.
- Ejecución sin caché.
- Segunda ejecución con caché.
- Medición de tiempo, memoria y estabilidad.

### Regresión obligatoria

- [x] Ejecutar todas las pruebas automatizadas.
- [x] Ejecutar el lote dorado CR2.
- [x] Comparar asignaciones CR2 antes y después.
- [x] Confirmar que Full RAW CR3 nunca se ejecuta para CR2.
- [x] Confirmar que los cachés permanecen separados.
- [x] Compilar el motor.
- [x] Sincronizar el sidecar utilizado por Tauri.
- [x] Compilar el instalador.
- [x] Instalar desde cero.
- [x] Ejecutar la clasificación desde el `.exe` instalado.
- [x] Revisar JSON, TXT, XLSX y carpetas entregadas.

### Condición de cierre

La aplicación instalada debe reproducir los resultados aprobados del entorno de desarrollo y mantener intacta la clasificación CR2.

---

## 9. Criterios finales de aprobación

CR3 se declarará en paridad con CR2 únicamente cuando cumpla todos estos puntos:

- [ ] Cero regresiones comprobadas en CR2.
- [ ] Misma versión de RetinaFace y ArcFace.
- [ ] Precisión CR3 igual o superior a CR2 en un conjunto comparable.
- [ ] Cobertura CR3 como máximo dos puntos porcentuales debajo de CR2.
- [ ] Referencias naturales, sin seleccionar manualmente una imagen favorable.
- [ ] Ausencia de mezclas sistemáticas entre alumnos.
- [ ] Fotografías grupales correctamente manejadas por rostro.
- [ ] Códigos repetidos resueltos entre varios salones.
- [ ] Registros aislados por usuario.
- [ ] Resultados consistentes en ejecuciones sin caché.
- [ ] Resultados consistentes desde el ejecutable instalado.
- [ ] Informes completos y trazables.

No se utilizará un porcentaje único obtenido de una muestra pequeña para declarar éxito.

---

## 10. Protocolo de trabajo obligatorio

Para cada módulo se seguirá este ciclo:

1. Cambiar el estado del módulo a `EN PROCESO`.
2. Registrar el problema exacto que se resolverá.
3. Hacer una modificación pequeña y localizada.
4. Crear o actualizar pruebas del comportamiento.
5. Ejecutar las pruebas del módulo.
6. Ejecutar la regresión CR2.
7. Ejecutar la prueba CR3 correspondiente.
8. Comparar métricas contra la línea base.
9. Documentar resultados y decisiones.
10. Revertir el enfoque si reduce precisión o altera CR2.
11. Marcar el módulo `COMPLETADO` solamente si cumple su condición de cierre.
12. Comenzar el siguiente módulo.

No se realizarán cambios simultáneos en varios módulos porque impedirían identificar cuál modificación produjo una mejora o un fallo.

---

## 11. Registro de avances

Cada sesión de trabajo debe agregar una entrada con este formato:

```text
Fecha:
Módulo:
Objetivo de la sesión:
Archivos modificados:
Pruebas ejecutadas:
Resultado CR3:
Resultado de regresión CR2:
Decisión tomada:
Pendiente inmediato:
```

### Entradas

#### 10 de agosto de 2026 — creación del plan

- Módulo: planificación previa.
- Objetivo: documentar el camino completo hacia la paridad CR3/CR2.
- Archivos modificados: solamente este documento.
- Pruebas de referencia: 80/80 aprobadas antes de crear el plan.
- Resultado CR3 base: procesamiento estable, reconocimiento aún por debajo de CR2.
- Resultado CR2: no se modificó el motor durante la creación del plan.
- Decisión: comenzar posteriormente por el Módulo 0 y no saltar etapas.
- Pendiente inmediato: congelar formalmente la línea base y crear el lote dorado CR2.

#### 10 de agosto de 2026 — cierre del Módulo 0

- Módulo: 0, congelar y documentar la base.
- Objetivo: crear una regresión reproducible que impida cambios accidentales en JPG/CR2.
- Archivos modificados: plan maestro, línea base JSON, reporte de línea base Markdown y dos utilidades de prueba; ningún archivo productivo.
- Pruebas ejecutadas: 80/80 iniciales y 83/83 después de agregar tres pruebas del verificador.
- Resultado CR3: se conservaron por ruta y SHA-256 los dos reportes base existentes; no se cambió la ruta CR3.
- Resultado de regresión CR2: dos ejecuciones completas sin caché aprobaron 22/22 referencias, 130 fotos únicas, 259 archivos entregados, 0 errores y 0 conflictos, con la misma firma exacta de asignaciones.
- Compilación: Python, Vite de producción y Cargo `release` aprobados.
- Integridad: motor, `bridge`, dependencias, ejecutables sidecar e instalador conservaron sus hashes iniciales.
- Decisión: el lote mixto completo de 1,810 archivos es la única verdad semántica; el subconjunto CR2 puro queda únicamente como control de lectura RAW.
- Pendiente inmediato: solicitar autorización antes de marcar e iniciar el Módulo 1.

#### 10 de agosto de 2026 — cierre del Módulo 1

- Módulo: 1, medición facial y verdad de referencia.
- Objetivo: explicar cada resultado CR3 con una verdad etiquetada y mediciones reproducibles, sin alterar decisiones del clasificador.
- Archivos modificados: manifiesto CR3, evaluador diagnóstico, ejecutor del sidecar, pruebas, reportes del módulo y un comando diagnóstico aislado en `bridge.py`.
- Pruebas ejecutadas: 86/86 pruebas Python aprobadas; dos mediciones completas de 31 CR3 idénticas byte por byte; compilación Python, Vite de producción y Cargo `release` aprobadas.
- Resultado CR3: 31/31 archivos decodificados y con detección en preview y Full RAW. La ejecución natural conserva 100% de precisión y 8.7% de cobertura (2/23); el control favorable conserva 100% de precisión y 78.3% de cobertura (18/23).
- Resultado de regresión CR2: aprobada con la misma firma exacta de 259 asignaciones del lote dorado.
- Integridad: `engine/tools/facesync_tools.py` conserva el SHA-256 congelado `9426F4BE570EF66CF897AB29E1FC3446579633651D3AC1757EE2C3A0FFD326D6`; no cambiaron umbrales ni decisiones de clasificación JPG/CR2/CR3.
- Decisión: conservar preview y Full RAW como mediciones separadas; usar distancias leave-one-out solamente como diagnóstico y no como galería de producción; no guardar embeddings en los reportes.
- Pendiente inmediato: solicitar autorización expresa antes de iniciar el Módulo 2.

#### 11 de agosto de 2026 — cierre del Módulo 2

- Módulo: 2, diagnóstico de las dos representaciones CR3.
- Objetivo: determinar con matrices completas cuándo preview o Full RAW conserva mejor la identidad, sin modificar parámetros ni decisiones del clasificador.
- Archivos modificados: evaluador diagnóstico CR3, manifiesto con secuencias, comando aislado del `bridge`, ejecutor del sidecar, generador de reportes, pruebas y artefactos del Módulo 2.
- Pruebas ejecutadas: 87/87 pruebas Python aprobadas; dos mediciones limpias de 31 CR3 y cinco artefactos derivados idénticos byte por byte; compilación Python, Vite de producción y Cargo `release` aprobadas.
- Resultado CR3: se generaron 465 pares por ruta y una matriz cruzada de 961 comparaciones. Preview obtuvo AUC diagnóstica 0.9309 y Full RAW 0.9891 sobre rostros detectados. Preview fue más coherente en `ATLETA_SERIE_00`; Full RAW en `ATLETA_SERIE_12` y `BAILARINA_SERIE`.
- Sensibilidad: en pares que incluyen exposición extrema, la mediana preview fue 0.8259 y Full RAW 0.2475. Se encontraron dos cambios de orientación; `_R4A4513.cr3` usó en preview un respaldo de imagen completa con confianza 0, mientras Full RAW sí detectó el rostro.
- Omisiones: con galería de verdad diagnóstica, 17 fotos preview y 20 Full RAW resultaron limitadas principalmente por la referencia natural; quedaron 3 casos difíciles en preview, 1 en Full RAW y 1 respaldo preview sin detección real.
- Resultado de regresión CR2: aprobada con la misma firma exacta de 259 asignaciones del lote dorado.
- Integridad: `engine/tools/facesync_tools.py` conserva su SHA-256 congelado; no cambiaron ArcFace, RetinaFace, umbrales ni reglas de clasificación.
- Decisión: no seleccionar una ruta global. Preview y Full RAW deben permanecer separados y la estrategia futura deberá escoger evidencia por identidad o secuencia, sin mezclar embeddings.
- Pendiente inmediato: solicitar autorización expresa antes de iniciar el Módulo 3.

#### 11 de agosto de 2026 — cierre del Módulo 3

- Módulo: 3, fortalecimiento de la referencia CR3.
- Objetivo: permitir que la referencia natural produzca una representación operativa respaldada sin cambiar el código raíz, el motor facial ni los umbrales generales.
- Archivos modificados: selector CR3 aislado, integración CR3 localizada, pruebas unitarias/integración, ejecutores de clasificación, reportes del módulo y plan maestro. No cambiaron ArcFace, RetinaFace ni sus parámetros.
- Pruebas ejecutadas: 98/98 pruebas Python aprobadas; pruebas específicas de referencia lateral, pequeña, grupal, rotación, ambigüedad, respaldo de confianza 0, aislamiento CR2/JPG y límite de trabajo Full RAW; Python, Vite de producción y Cargo `release` aprobados.
- Resultado CR3: las referencias naturales pasaron de 2/23 a 21/23 fotografías correctas. Precisión 100%, cobertura 91.3%, cero falsos positivos, cero duplicados y cero entregas ajenas al manifiesto.
- Selección: ATLETA conservó el código 9874 y la raíz `_R4A9874.cr3`; se promovió `_R4A1244.cr3` como ancla operativa Full RAW con 18 soportes. BAILARINA conservó su raíz porque el margen del mejor grupo frente al segundo fue 0.022418, inferior al margen existente 0.05; no se forzó una identidad.
- Reproducibilidad: tres corridas limpias consecutivas produjeron 21/23, la misma ancla y las mismas dos omisiones. El sidecar PyInstaller reprodujo exactamente el resultado.
- Resultado de regresión CR2: aprobada desde el sidecar nuevo con la misma firma exacta de 259 asignaciones del lote dorado.
- Empaquetado: sidecar reconstruido y sincronizado con Tauri; ambos ejecutables tienen SHA-256 `9FC3E0BB0EF30E3319EB63A2BE0D3AB4BF6506EBACCF6965EE561CDA085F1ED4`. No se construyó instalador.
- Decisión: cerrar el módulo porque la clasificación base fue superada claramente sin perder precisión. Las omisiones `_R4A4513.cr3` y `_R4A7192.cr3` quedan como entrada segura y medible para el arranque de galería del Módulo 4.
- Pendiente inmediato: solicitar autorización expresa antes de iniciar el Módulo 4.

#### 11 de agosto de 2026 — inicio del Módulo 4

- Módulo: 4, arranque seguro de la galería CR3.
- Objetivo: formar una galería inicial CR3 con múltiples evidencias coherentes y reevaluar las omisiones sin reducir la precisión.
- Archivos modificados al iniciar: solamente el plan maestro.
- Pruebas ejecutadas al iniciar: pendientes de la auditoría e implementación del módulo.
- Resultado CR3 de entrada: 21/23 fotografías correctas, 100% de precisión, 91.3% de cobertura y dos omisiones conocidas.
- Resultado de regresión CR2 de entrada: firma exacta de 259 asignaciones aprobada al cierre del Módulo 3.
- Decisión: trabajar exclusivamente en la capa CR3, conservar separados preview y Full RAW, mantener los umbrales 0.28/0.40 y detenerse antes del Módulo 5.
- Pendiente inmediato: auditar el flujo actual de galerías y definir el punto mínimo de integración.

#### 11 de agosto de 2026 — cierre del Módulo 4

- Módulo: 4, arranque seguro de la galería CR3.
- Objetivo: formar una galería inicial CR3 con múltiples evidencias coherentes y reevaluar omisiones sin reducir la precisión.
- Archivos modificados: nuevo arranque CR3 aislado, integración localizada en las rutas preview y Full RAW, reportes JSON/TXT/XLSX, pruebas, ejecutor diagnóstico y documentación. No cambiaron ArcFace, RetinaFace ni sus parámetros.
- Pruebas ejecutadas: 12/12 enfocadas y 107/107 de la suite Python aprobadas; compilación del código Python, Vite de producción, Cargo `release` y sidecar PyInstaller aprobados.
- Resultado CR3: las referencias naturales pasaron de 21/23 a 23/23 fotografías correctas; precisión 100%, cobertura 100%, cero falsos positivos, cero duplicados y cero entregas ajenas al manifiesto.
- Arranque: preview bloqueó correctamente el grupo por evidencia insuficiente. Full RAW aceptó `_R4A4513.cr3` y `_R4A7192.cr3` como dos alimentadores distintos de BAILARINA y recuperó ambas omisiones.
- Seguridad: un primer intento que asignó dos controles de muñeco fue rechazado. La incompatibilidad de escala facial permitió añadir una guarda conservadora exclusiva de CR3; dos repeticiones limpias posteriores y el sidecar produjeron 23/23 sin controles asignados.
- Resultado de regresión CR2: aprobada desde el sidecar nuevo con la misma firma exacta de 259 asignaciones del lote dorado.
- Empaquetado: sidecar reconstruido y sincronizado con Tauri; ambos ejecutables tienen SHA-256 `73DA69994B63FD62AF893DBFCC182AFFC62C7C08555ED0C9B287AA3432832211`. No se construyó instalador.
- Límite: la muestra real contiene dos identidades y no incluye una fotografía grupal real etiquetada; esas protecciones están probadas automáticamente, pero la paridad CR3 general todavía depende de los módulos y conjuntos restantes.
- Decisión: cerrar el módulo porque aumentó la cobertura sin reducir precisión y conservó exactamente la regresión CR2.
- Pendiente inmediato: detenerse y solicitar autorización expresa antes de iniciar el Módulo 5.

#### 11 de agosto de 2026 — inicio del Módulo 5

- Módulo: 5, decisión coordinada preview y Full RAW.
- Objetivo: coordinar decisiones independientes de ambas representaciones, conservar asignaciones seguras y auditar contradicciones sin mezclar embeddings.
- Archivos modificados al iniciar: solamente el plan maestro.
- Pruebas ejecutadas al iniciar: pendientes de la auditoría e implementación del módulo.
- Resultado CR3 de entrada: 23/23 fotografías correctas, 100% de precisión y 100% de cobertura sobre el conjunto real disponible.
- Resultado de regresión CR2 de entrada: firma exacta de 259 asignaciones aprobada al cierre del Módulo 4.
- Aceptación observable: conservar todas las decisiones base seguras; permitir rescates sólo con evidencia por rostro, margen y consenso; bloquear desacuerdos; registrar motivos; mantener 23/23 CR3 y la firma CR2 exacta.
- No objetivos: no cambiar ArcFace, RetinaFace, umbrales 0.28/0.40, caché histórico, SQLite, entrega genérica, JPG o CR2; no iniciar el Módulo 6.
- Pendiente inmediato: auditar dónde se forman, conservan y combinan actualmente las decisiones preview y Full RAW para elegir el punto mínimo de integración.

#### 11 de agosto de 2026 — cierre del Módulo 5

- Módulo: 5, decisión coordinada preview y Full RAW.
- Objetivo: coordinar decisiones independientes por rostro, conservar asignaciones preview seguras y bloquear contradicciones antes de entregar.
- Archivos modificados: árbitro CR3 aislado, integración localizada en la segunda ruta Full RAW, reportes JSON/TXT/XLSX, pruebas y documentación. No se modificó el resolvedor genérico.
- Pruebas ejecutadas: 13/13 específicas del árbitro y 120/120 de la suite Python aprobadas; compilación Python, Vite de producción, Cargo `release` y sidecar PyInstaller aprobados.
- Resultado CR3: dos corridas limpias y el sidecar produjeron 23/23 fotografías correctas, precisión 100%, cobertura 100%, cero falsos positivos, cero duplicados y cero entregas desconocidas.
- Arbitraje real: 14 objetivos CR3, cinco decisiones Full RAW confirmadas y cinco rescates aceptados por rostro. `_R4A4513.cr3` y `_R4A7192.cr3` conservaron dos soportes de galería cada una.
- Seguridad: las pruebas comprobaron no reemplazo preview, consenso, margen, contradicción, confianza 0, geometría grupal y múltiples identidades dentro de una misma fotografía.
- Resultado de regresión CR2: aprobada desde el sidecar nuevo con la misma firma exacta de 259 asignaciones del lote dorado.
- Empaquetado: sidecar reconstruido y sincronizado con Tauri; ambos ejecutables tienen SHA-256 `BA52A8684E6EADCFEB5E6C612BA250FA1BD402CD0B62935207D0953F512F410F`. No se construyó instalador.
- Límite: el conjunto real contiene dos identidades, sin grupo real etiquetado ni contradicción real entre rutas; esos casos aprobaron pruebas automatizadas, pero requieren validación real más amplia para declarar paridad general.
- Decisión: cerrar el módulo porque la segunda ruta recupera evidencia por rostro sin sustituir decisiones seguras, no crea mezclas y conserva exactamente CR2.
- Pendiente inmediato: detenerse y solicitar autorización expresa antes de iniciar el Módulo 6.

#### 11 de agosto de 2026 — inicio del Módulo 6

- Módulo: 6, registro histórico y caché consciente de ruta.
- Objetivo: guardar evidencia CR3 confirmada con representación y versión para resolver códigos repetidos entre salones sin mezclar rutas, formatos ni usuarios.
- Archivos modificados al iniciar: solamente el plan maestro.
- Pruebas ejecutadas al iniciar: pendientes de la auditoría del esquema, lectores y escritores actuales.
- Resultado CR3 de entrada: 23/23 fotografías correctas, precisión y cobertura 100% sobre el conjunto real disponible.
- Resultado de regresión CR2 de entrada: firma exacta de 259 asignaciones aprobada al cierre del Módulo 5.
- Ruta de migración: expandir el esquema de forma aditiva e idempotente, mantener lectura de registros anteriores y escribir metadatos de ruta sólo para evidencia CR3 confirmada.
- Ruta de reversión: el código anterior debe poder ignorar las columnas o tablas nuevas; no se eliminarán ni reescribirán datos existentes y no habrá contracción destructiva.
- Aceptación observable: el mismo código CR3 debe distinguir identidades en segundo y tercer salón mediante registros por usuario/ruta; la limpieza de caché no debe borrar el historial; CR2 y usuarios ajenos deben conservar su comportamiento exacto.
- No objetivos: no cambiar ArcFace, RetinaFace, umbrales, árbitro del Módulo 5, clasificación JPG/CR2 ni iniciar el Módulo 7.
- Pendiente inmediato: mapear esquema SQLite, lectores, escritores, claves de cuenta, limpieza y selección histórica antes de editar código.

#### 11 de agosto de 2026 — cierre del Módulo 6

- Estado: `COMPLETADO`.
- Migración: SQLite pasó de esquema 1 a 2 mediante una tabla aditiva `identity_route_records`; la tabla histórica de JPG/CR2 no se alteró, los registros anteriores siguen legibles y la migración es idempotente.
- Separación CR3: preview y Full RAW se guardan como registros independientes con formato, representación y versión; una repetición sólo sustituye la misma ruta de la misma identidad y salón.
- Caché: la representación principal usa `cr3_preview_v1`, el índice usa `cr3_index_preview_v1` y Full RAW conserva `cr3_fullraw_v1`; las claves y carpetas CR2 permanecen sin cambios.
- Historial: una referencia CR3 sólo se compara contra anclajes de la misma representación y versión. JPG/CR2 nunca consultan registros CR3 conscientes de ruta.
- Evidencia guardada: código, alumno, salón, Excel, orígenes, raíz, hash, ruta, versión, embedding principal, anclajes confirmados, soportes, coherencia, fecha y cámara cuando existe; el reporte público no expone embeddings.
- Seguridad: sólo se registra una identidad con soporte visual múltiple; el registro etiquetado vive fuera del caché desechable y permanece tras limpiar conversiones y embeddings.
- Pruebas automatizadas: `129/129` aprobadas. Incluyen migración v1→v2, reapertura idempotente, coexistencia preview/Full RAW, segundo y tercer salón, descarte de dos propietarios anteriores, aislamiento entre cuentas, cierre/reapertura y limpieza de caché sin pérdida histórica.
- Resultado CR3 desde código fuente: `23/23`, precisión `100%`, cobertura `100%`, cero errores RAW y cero errores de imagen.
- Resultado CR3 desde sidecar: `23/23`, precisión `100%`, cobertura `100%`; SQLite v2 registró tres rutas reales confirmadas: ATLETA preview, ATLETA Full RAW y BAILARINA Full RAW.
- Resultado CR2: regresión dorada aprobada desde el sidecar nuevo con la firma exacta de `259` asignaciones.
- Compilación: Python, Vite de producción, Cargo `release` y PyInstaller aprobados.
- Sidecar: motor y recurso Tauri sincronizados con SHA-256 `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Empaquetado: no se construyó instalador final.
- Evidencia: `docs/baselines/module6/MODULE_6_CR3_ROUTE_HISTORY.md` y `docs/baselines/module6/MODULE_6_CR3_ROUTE_HISTORY.json`.
- Pendiente inmediato: detenerse y solicitar autorización expresa antes de iniciar el Módulo 7.

---

## 12. Registro de decisiones técnicas

| Fecha | Módulo | Decisión | Evidencia | Impacto en CR2 |
|---|---|---|---|---|
| 2026-08-10 | Planificación | Mantener preview y Full RAW como espacios separados | Solo 6/31 embeddings fueron prácticamente equivalentes entre rutas | Ninguno |
| 2026-08-10 | Planificación | No cambiar umbrales antes del diagnóstico | La referencia favorable mejoró la cobertura sin cambiar umbrales | Ninguno |
| 2026-08-10 | Planificación | Priorizar referencia y arranque de galería | Las referencias naturales tuvieron cero apoyos visuales | Ninguno |
| 2026-08-10 | Planificación | Proteger CR2 mediante una capa exclusiva CR3 | La ruta Full RAW ya está aislada por formato y caché | Ninguno |
| 2026-08-10 | Módulo 0 | Usar el lote mixto completo como verdad dorada | Dos ejecuciones sin caché produjeron la misma firma exacta de 259 asignaciones | Ninguno |
| 2026-08-10 | Módulo 0 | Usar el subconjunto CR2 puro solo como prueba de I/O | Procesó 130/130 RAW sin error, pero retirar negativos alteró el contexto semántico | Ninguno |
| 2026-08-10 | Módulo 0 | No reconstruir el motor congelado | El ejecutable actual aprobó dos regresiones y ningún archivo productivo cambió | Se conserva exactamente la versión aprobada |
| 2026-08-10 | Módulo 1 | Añadir medición mediante un comando diagnóstico aislado | Dos ejecuciones de 31 CR3 produjeron JSON idénticos byte por byte | Regresión exacta de 259 asignaciones aprobada |
| 2026-08-10 | Módulo 1 | No exportar embeddings y no usar la galería leave-one-out en producción | El reporte sólo conserva cajas, confianza y distancias; algunos negativos muestran cercanía diagnóstica peligrosa | Ninguno |
| 2026-08-10 | Módulo 1 | Mantener preview y Full RAW separados | Ambas rutas procesaron 31/31, pero sus distancias cambian de forma material según la fotografía | Ninguno |
| 2026-08-11 | Módulo 2 | No elegir una representación global | Preview ganó `ATLETA_SERIE_00`; Full RAW ganó `ATLETA_SERIE_12` y `BAILARINA_SERIE` | Regresión exacta de 259 asignaciones aprobada |
| 2026-08-11 | Módulo 2 | Separar detecciones reales de respaldos con confianza 0 | `_R4A4513.cr3` produjo un embedding de imagen completa en preview y un rostro válido en Full RAW | Ninguno |
| 2026-08-11 | Módulo 2 | Mantener controles sin persona fuera de la distribución de humanos distintos | Los muñecos generan detecciones y distancias extremas que no representan separación entre alumnos | Ninguno |
| 2026-08-11 | Módulo 2 | No ajustar todavía el umbral 0.28 | El problema cambia por secuencia, exposición y ruta; el módulo sólo autoriza diagnóstico | Ninguno |
| 2026-08-11 | Módulo 3 | Mantener la fotografía y el código raíz como autoridad y usar una sola ancla operativa interna | La referencia 9874 ganó 18 soportes sin sustituir el código del Excel | Regresión exacta de 259 asignaciones aprobada |
| 2026-08-11 | Módulo 3 | Exigir correspondencia geométrica entre rutas y bloquear confianza 0 | Las pruebas grupales/rotadas aprobaron y el respaldo preview de `_R4A4513.cr3` no pudo convertirse en ancla | Ninguno |
| 2026-08-11 | Módulo 3 | No forzar el grupo de BAILARINA | Su margen 0.022418 no alcanzó el mínimo existente 0.05; conservar la raíz evitó falsos positivos | Ninguno |
| 2026-08-11 | Módulo 3 | Limitar Full RAW a 30 candidatos por rostro más las raíces | Una prueba de 101 CR3 procesó sólo 31 en el selector, manteniendo escala lineal por referencia | Ninguno |
| 2026-08-11 | Módulo 4 | Usar búsqueda amplia sólo para formar grupos, nunca para entregar directamente | Las dos omisiones se recuperaron después de crear dos anclajes y reevaluarlas con las reglas existentes | Ninguno |
| 2026-08-11 | Módulo 4 | Exigir dos fotografías distintas, confianza real y separación frente a referencias y galerías | Las pruebas bloquearon evidencia aislada, respaldos con confianza 0, rostros ajenos y acompañantes | Ninguno |
| 2026-08-11 | Módulo 4 | Añadir una guarda conservadora de compatibilidad de escala facial exclusiva de CR3 | El primer intento produjo dos falsos positivos de muñeco; tras la guarda, dos corridas y el sidecar dieron 23/23 sin falsos positivos | Regresión exacta de 259 asignaciones aprobada |
| 2026-08-11 | Módulo 4 | Mantener preview y Full RAW como arranques independientes | Preview quedó bloqueado por una sola evidencia real; Full RAW formó el grupo correcto con dos alimentadores | Ninguno |
| 2026-08-11 | Módulo 5 | Reemplazar únicamente la unión final CR3 por un árbitro puro por rostro | El resolvedor ya generaba decisiones separadas; la unión anterior sólo auditaba algunas asignaciones confirmadas | Ninguno |
| 2026-08-11 | Módulo 5 | Relacionar rutas por geometría normalizada y conservar embeddings separados | Las pruebas grupales asignaron dos identidades por rostros diferentes y bloquearon correspondencias ambiguas | Ninguno |
| 2026-08-11 | Módulo 5 | Hacer inmutable toda asignación preview segura | Una prueba enfrentó una decisión Full RAW distinta y conservó exclusivamente el propietario preview | Ninguno |
| 2026-08-11 | Módulo 5 | Exigir distancia segura o consenso de galería y margen frente a otras identidades | 13/13 pruebas del árbitro y dos corridas reales 23/23 sin falsos positivos | Regresión exacta de 259 asignaciones aprobada |
| 2026-08-11 | Módulo 6 | Crear una tabla SQLite aditiva exclusiva para historial CR3 por ruta | Evita que preview y Full RAW se sustituyan y permite que versiones anteriores ignoren la expansión | La tabla y las escrituras JPG/CR2 permanecen intactas |
| 2026-08-11 | Módulo 6 | Versionar por separado cachés preview, índice preview y Full RAW | Las tres representaciones CR3 tienen claves distintas y la limpieza no elimina el historial | Las claves y carpetas CR2 no cambiaron |
| 2026-08-11 | Módulo 6 | Comparar historial sólo dentro de la misma representación y versión | Pruebas bloquearon preview→Full RAW, CR3→legacy y descartaron dos propietarios previos en un tercer salón | JPG/CR2 conservan la selección histórica anterior y la firma dorada exacta |

---

## 13. Próxima acción autorizable

Los **Módulos 0, 1, 2, 3, 4, 5, 6 y 7** están completados. El **Módulo 8: validación integral y preparación de producción** agotó todas las comprobaciones disponibles y quedó `BLOQUEADO` únicamente por falta de los conjuntos reales obligatorios de los Niveles 2, 3 y 4. La cadena técnica, el instalador y la regresión CR2 están aprobados.

#### 11 de agosto de 2026 — inicio del Módulo 7

- Módulo: 7, calibración CR3 basada en datos.
- Objetivo: determinar con distribuciones verdaderas y falsas si algún parámetro exclusivo CR3 necesita ajuste después de los Módulos 3 a 6.
- Configuración de entrada: CR3 real `23/23`, precisión y cobertura `100%`; CR2 dorado con `259` asignaciones exactas.
- Orden obligatorio: medir configuración actual, separar ajuste/validación, justificar cualquier cambio, validar con identidades no usadas para ajustar y comparar nuevamente con CR2.
- Límites congelados: ArcFace, RetinaFace, umbrales generales `0.28/0.40`, reglas JPG/CR2, árbitro aprobado y registro histórico del Módulo 6.
- Regla de decisión: si los datos no demuestran una mejora segura o no permiten una validación independiente suficiente, la calibración será un `no-op` documentado y no se tocará código productivo.
- No objetivos: no iniciar producción/empaquetado del Módulo 8 ni construir instalador.
- Pendiente inmediato: inventariar todas las identidades CR3 etiquetables disponibles antes de medir o editar parámetros.

#### 11 de agosto de 2026 — cierre del Módulo 7

- Estado: `COMPLETADO` como calibración `no-op` basada en evidencia.
- Inventario: las `23` muestras Canon descargadas eran copias SHA-256 exactas del lote base; cuatro CR3 sí eran inéditos.
- Evidencia inédita: una foto con dos personas desconocidas y tres fotos sin persona. Se usaron como controles negativos; no se usaron para ajustar parámetros.
- Resultado fuente: `35/35` CR3 procesados, `23/23` objetivos correctos, precisión y cobertura `100%`, `12/12` controles rechazados y cero errores RAW o de imagen.
- Resultado sidecar: mismo resultado exacto; SHA-256 `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Decisión: no cambiar ningún parámetro CR3 porque no existe error observable que corregir y las nuevas identidades no tienen fotografías repetidas para sostener una calibración positiva independiente.
- Protección: ArcFace, RetinaFace, umbrales `0.28/0.40`, reglas JPG/CR2 y código productivo permanecieron sin cambios.
- Regresión: `129/129` pruebas, compilación Python, Vite y `cargo check --release` aprobados; CR2 conservó la firma exacta de `259` asignaciones.
- Entregables: `docs/baselines/module7/MODULE_7_CR3_DATA_CALIBRATION.md` y `.json`.
- Limitación explícita: la validación comercial amplia con más identidades repetidas, grupos y cámaras corresponde al Módulo 8.
- Pendiente inmediato: detenerse y solicitar autorización expresa antes de iniciar el Módulo 8.

#### 11 de agosto de 2026 — inicio del Módulo 8

- Módulo: 8, producción, regresión y empaquetado.
- Objetivo: comprobar la misma conducta aprobada en código, sidecar, aplicación empaquetada e instalación limpia.
- Método: convertir cada nivel y cada punto de regresión en una prueba verificable; reutilizar únicamente evidencia cuya versión siga siendo idéntica.
- Estado de entrada: Módulos 0 a 7 completados; CR3 `23/23`, controles `12/12`, CR2 con `259` asignaciones exactas y `129/129` pruebas aprobadas.
- Límites: verificación primero; no cambiar código productivo, umbrales, ArcFace, RetinaFace ni reglas JPG/CR2 sin una falla reproducible y una causa demostrada.
- Regla de reporte: cada criterio quedará como `APROBADO`, `FALLÓ`, `NO DISPONIBLE` o `BLOQUEADO`; no se declarará paridad general a partir de la muestra pequeña actual.
- Pendiente inmediato: construir una matriz de evidencia para los seis niveles y ejecutar primero las comprobaciones disponibles de menor costo.

#### 11 de agosto de 2026 — cierre técnico y bloqueo por datos del Módulo 8

- Estado: `BLOQUEADO`; no se encontró una falla de código.
- Nivel 1: aprobado con `35/35` CR3 procesados, `23/23` objetivos correctos, `12/12` controles rechazados y cero errores.
- Nivel 2: no disponible; sólo existen dos identidades reales repetidas y el plan exige al menos cinco.
- Nivel 3: no disponible; no existe un salón CR3 etiquetado de 15 a 30 alumnos con grupos y acompañantes.
- Nivel 4: lógica automatizada aprobada para segundo/tercer salón, reapertura, historial y aislamiento; falta el lote real de tres salones CR3.
- Nivel 5: aprobado con `1,841` imágenes JPG/CR2/CR3; `259` asignaciones CR2/JPG exactas y `23/23` CR3 correctos.
- Nivel 6: aprobado como volumen técnico con `1,000` CR3, cero errores, salida fría/caliente idéntica, `804.594 s` sin caché, `34.859 s` con caché y aceleración `23.0814x`.
- Regresión: `129/129` pruebas; CR2 instalado conservó `259` asignaciones exactas, `130 CR2 + 129 JPG`, y Full RAW CR3 procesó `0` CR2.
- Empaquetado: Python, Vite, Cargo release, PyInstaller, Tauri y NSIS aprobados.
- Instalador: `FaceSync_1.0.0_x64-setup.exe`, SHA-256 `5166D1C89FC8ADA831A9622BE55AB285AA29DF1AA55218E10C500DD26997B54E`.
- Instalación limpia: aprobada en ruta aislada; la aplicación abrió, respondió y su motor reprodujo CR3 y CR2. La instalación anterior y sus datos no se modificaron.
- Sidecar: origen, recurso Tauri y motor instalado conservaron SHA-256 `2D4C9B1A5DA908294A7E292C3713CC04D6EBE30AAB349289975AADDECFEBC7CB`.
- Reportes: JSON, TXT, XLSX y carpetas revisados; XLSX legible, 21 hojas y cero errores de fórmula.
- Protección: no se modificó código productivo, RetinaFace, ArcFace, umbrales generales ni comportamiento JPG/CR2 en este módulo.
- Evidencia: `docs/baselines/module8/MODULE_8_PRODUCTION_VALIDATION.md` y `.json`.
- Pendiente para desbloquear: aportar cinco identidades CR3 repetidas, un salón CR3 representativo y tres salones CR3 con un código raíz reutilizado por personas distintas.
