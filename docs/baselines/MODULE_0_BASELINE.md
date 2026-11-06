# Módulo 0 — Línea base congelada JPG/CR2

Fecha: 10 de agosto de 2026  
Estado: **COMPLETADO**

## Alcance

Esta línea base protege el funcionamiento aprobado de JPG y CR2 durante el trabajo exclusivo de CR3. En este módulo no se modificó el motor, ArcFace, RetinaFace, los umbrales, la selección de referencias, las auditorías, el caché de producción ni las reglas de entrega.

El archivo legible por máquina es `docs/baselines/MODULE_0_CR2_BASELINE.json`.

## Lote dorado

- Origen: `C:\Users\ianca\Desktop\piloto1\FRANK`
- Excel: `C:\Users\ianca\Desktop\piloto1\501m.xlsx`
- Hoja y rango: `Listado de Fotos!A1:B23`
- Alumnos: `22`
- Referencias: `22`
- Archivos de origen: `1,810`
  - JPG: `1,206`
  - CR2: `604`
- Ejecución: ejecutable empaquetado, cuenta aislada y `LOCALAPPDATA` vacío.

## Resultado dorado sin caché

| Métrica | Resultado |
|---|---:|
| Referencias encontradas | 22/22 |
| Fotos analizadas declaradas | 1,810 |
| Imágenes únicas procesadas | 1,207 |
| Fotos únicas clasificadas | 130 |
| Archivos entregados | 259 |
| JPG entregados | 129 |
| CR2 entregados | 130 |
| Fotos ignoradas no asignadas | 948 |
| Errores de imagen | 0 |
| Conflictos de identidad | 0 |
| Aciertos de caché de embeddings | 0% |
| Full RAW CR3 ejecutado | No |
| Backend | ONNX DirectML |
| Tiempo observado inicial | 475.403 s |

La firma SHA-256 del manifiesto exacto de asignaciones es:

```text
471F9281458F5A3A28F49FE1243757C44F8AA8750CB1E4E7EAC6594A4F8C30EE
```

El tiempo se registra como dato de rendimiento, pero no bloquea la regresión porque depende de carga, temperatura, disco y GPU. Las asignaciones, conteos, referencias y errores sí son condiciones exactas.

## Repetición automatizada

El comando único ejecuta el lote desde cero con caché aislado y después compara automáticamente el resultado:

```powershell
& 'C:\Users\ianca\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'engine\tests\run_cr2_golden_regression.py' --run-root '.codex_tmp\cr2_regression_nueva'
```

La carpeta indicada en `--run-root` debe ser nueva o estar vacía. Cada ejecución debe usar un nombre distinto.

Para verificar un resultado ya existente sin repetir el procesamiento:

```powershell
& 'C:\Users\ianca\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'engine\tests\run_cr2_golden_regression.py' --report 'RUTA\_reporte_facesync.json' --destination 'RUTA_DESTINO'
```

La repetición automática realizada al cerrar el módulo aprobó la misma firma, las mismas 259 entregas y los mismos conteos de los 22 alumnos. Su tiempo fue `616.649 s`, sin caché, con `0` errores de imagen y `0` conflictos de identidad.

## Control adicional CR2 puro

Se procesaron sin JPG gemelos los 130 CR2 positivos entregados por la prueba mixta:

- CR2 detectados: `130`.
- Embeddings calculados: `130`.
- Aciertos de caché: `0%`.
- Errores RAW: `0`.
- Errores de imagen: `0`.
- Tiempo: `52.019 s`.

Este control confirma lectura, conversión, prefetch y extracción facial CR2. No se usa como verdad semántica porque retirar las 474 fotografías negativas cambia el contexto de la galería y de las auditorías. La única verdad de clasificación es el lote completo real de 1,810 archivos.

## Pruebas y compilación

- Suite inicial antes de agregar el verificador: `80/80` aprobadas.
- Suite final con tres pruebas del verificador: `83/83` aprobadas.
- Compilación de todos los archivos Python: aprobada.
- Build Vite de producción: aprobado, 49 módulos transformados.
- `cargo check --release`: aprobado.
- Ejecutable empaquetado: ejecutó dos veces el lote dorado completo.

No se reconstruyó el motor ni el instalador porque ningún archivo productivo cambió y ambos forman parte de la versión congelada. Sus hashes se comprobaron al cierre y permanecen idénticos.

## Integridad confirmada

- `engine/tools/facesync_tools.py`: sin cambios.
- `engine/bridge.py`: sin cambios.
- `engine/requirements.txt`: sin cambios.
- Suite productiva de paridad existente: sin cambios.
- Ejecutable del motor y sidecars Tauri: mismo SHA-256.
- Instalador NSIS: mismo SHA-256.
- Fuentes del frontend: mismo manifiesto SHA-256.
- Únicos archivos fuente nuevos: línea base y utilidades de prueba del Módulo 0.

## Criterio de bloqueo para módulos posteriores

Después de cada cambio CR3 se deben ejecutar las pruebas automatizadas y el comando dorado. Si cambia una asignación JPG/CR2, un conteo, una referencia, aparece un error, CR3 Full RAW se ejecuta sobre CR2 o el verificador devuelve código distinto de cero, el módulo en curso no puede cerrarse.
