# Uruguay DUA Comex

Datos de comercio exterior de Uruguay (importaciones, exportaciones y tránsitos), a partir de las declaraciones aduaneras (DUA) que publica la Dirección Nacional de Aduanas (DNA), en un formato limpio y fácil de consultar.

Creado por: Fernanda Aguirre Ruiz

---

## ¿Qué es esto?

La DNA publica a diario, por ley, el detalle de todas las declaraciones aduaneras de Uruguay (Ley 19.438, art. 43): qué se importó o exportó, con quién, por qué monto, desde/hacia qué país, etc. Ese archivo crudo es difícil de usar directamente (viene en XML, con códigos internos, sin unificar meses ni corregir declaraciones modificadas o anuladas).

Este proyecto toma esos archivos crudos y arma **una sola tabla limpia** (2016 a 2026), con nombres de columna entendibles en vez de códigos, lista para explorar sin necesidad de saber programar para usarla.

---

## Por dónde empezar

**Si solo querés buscar datos (sin programar):**
Abrí [`notebooks/0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) en Jupyter, cambiá los valores de la celda de configuración (años, nombre de empresa, código NCM) y ejecutá. Te deja el resultado también exportado en Excel/CSV en `outputs/tables/`.

**Si preferís la terminal:**
```bash
python -m uruguay_dua_comex.query --years 2024 --ncm 2701 --nombre "acme"
```
Ver todas las opciones con `--help`. Más ejemplos en [Consultar los datos](#consultar-los-datos) más abajo.

**Si querés entender o modificar cómo se arma el dataset:**
Mirá [El pipeline de datos](#el-pipeline-de-datos): son 3 notebooks numerados, se corren en orden.

---

## Instalación

Este proyecto usa [`uv`](https://docs.astral.sh/uv/) para manejar Python y las dependencias (ya viene todo definido en `pyproject.toml`/`uv.lock`, no hay que instalar nada a mano).

```bash
git clone <url-del-repo>
cd uruguay_dua_comex
uv sync
```

Eso crea un entorno virtual (`.venv`) con todo lo necesario.

---

## Conseguir los datos

La tabla final (`dua_2016-2026_decoded.parquet`) se descarga sola la primera vez que hace falta — no hay que hacer nada a mano. En cuanto corrés una consulta (notebook `0.3` o la CLI) y el archivo todavía no está en `data/processed/`, se baja automáticamente desde el [release más reciente](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) del repositorio (con barra de progreso), y queda guardado ahí para las próximas veces.

Si en cambio querés armar la tabla por tu cuenta desde cero (por ejemplo, para actualizarla con meses más recientes), hace falta primero descargar los archivos crudos que publica la DNA (uno por mes, formato `dmYYYYMM.zip`) y guardarlos en `data/raw/<año>/`; estos archivos están disponibles públicamente en [aduanas.gub.uy](https://www.aduanas.gub.uy) en cumplimiento de la Ley 19.438, art. 43. Después corré los notebooks `0.1` y `0.2` en orden (ver [El pipeline de datos](#el-pipeline-de-datos)).

---

## El pipeline de datos

Tres notebooks, pensados para correrse en orden (cada uno depende del archivo que arma el anterior):

| Notebook | Qué hace | Entrada | Salida |
|---|---|---|---|
| [`0.1-convert-parquet.ipynb`](notebooks/0.1-convert-parquet.ipynb) | Une todos los archivos mensuales crudos en una sola tabla, aplicando altas, modificaciones y anulaciones en el orden correcto. | `data/raw/<año>/*.zip` | `data/processed/dua_<inicio>-<fin>.parquet` |
| [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb) | Traduce los códigos internos de la DNA que se pueden verificar contra una fuente oficial (ej. tipo de régimen, tipo de documento) y renombra todas las columnas a nombres entendibles. | `dua_<inicio>-<fin>.parquet` | `dua_<inicio>-<fin>_decoded.parquet` |
| [`0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) | Consulta el dataset final por año, régimen, empresa y/o NCM, y exporta el resultado. | `dua_<inicio>-<fin>_decoded.parquet` | Excel/CSV/Parquet en `outputs/tables/` |

Cada notebook explica en su primera celda, en detalle, las reglas y fuentes oficiales detrás de sus decisiones (por ejemplo, qué códigos se pudieron traducir con certeza y cuáles no).

---

## Consultar los datos

La lógica de consulta vive en [`uruguay_dua_comex/query.py`](uruguay_dua_comex/query.py) y funciona igual desde un notebook o desde la terminal.

**Filtros disponibles** (al menos `nombre` o `ncm` es obligatorio, para no escanear las ~20 millones de filas sin acotar):

| Filtro | Qué es | Ejemplo |
|---|---|---|
| `years` | Año o lista de años | `2024` / `[2023, 2024, 2025]` |
| `tipo_regimen` *(opcional)* | Importación (`i`), Exportación (`e`) o Tránsito (`t`) | `"i"` / `["i", "e"]` |
| `nombre` *(opcional)* | Nombre del importador/exportador (busca coincidencia parcial). Cuanto más específico, mejor: un término corto puede devolver miles de resultados. | `"acme"` |
| `ncm` *(opcional)* | Código NCM o prefijo (los puntos son opcionales: `78.01` = `7801`) | `"2701"` |

**Desde un notebook:**
```python
from uruguay_dua_comex.query import query_dua, export_query_result

resultado = query_dua(years=[2024, 2025], tipo_regimen="i", ncm="2701")
export_query_result(resultado, [2024, 2025], "i", None, "2701", formato="xlsx")
```

**Desde la terminal:**
```bash
python -m uruguay_dua_comex.query --years 2024 2025 -r i -n 2701 -f xlsx
```
Por defecto exporta un CSV al directorio donde estás parado/a; usá `--output`/`-o` para elegir otra carpeta y `--formato`/`-f` para elegir entre `csv`, `xlsx` o `parquet`. Ver todas las opciones con `--help`.

---

## Diccionario de datos

La especificación oficial de la DNA para estos archivos está en [`docs/FormatoDUADiariosPublicos.htm`](docs/FormatoDUADiariosPublicos.htm). La tabla completa de qué significa cada columna del dataset final (nombre original de la DNA, nombre nuevo, y si su código fue traducido o no, con la fuente oficial de cada decisión) está en la primera celda de [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb).

---

## Estructura del proyecto

```
uruguay_dua_comex/
├─ uruguay_dua_comex/         # Paquete de Python del proyecto
│  ├─ utils.py                # Rutas a las carpetas del proyecto (data_raw_dir, etc.)
│  └─ query.py                # Consulta y exportación del dataset (librería + CLI)
│
├─ notebooks/                 # El pipeline, en 3 pasos numerados (ver más arriba)
│  ├─ 0.1-convert-parquet.ipynb
│  ├─ 0.2-decode-data.ipynb
│  └─ 0.3-query-data.ipynb
│
├─ data/
│  ├─ raw/                    # Archivos originales de la DNA, sin tocar
│  ├─ interim/                # Archivos intermedios de 0.1 (uno por mes)
│  └─ processed/              # Tablas finales, listas para consultar
│
├─ docs/
│  └─ FormatoDUADiariosPublicos.htm   # Especificación oficial de la DNA
│
├─ outputs/
│  ├─ tables/                 # Exports de consultas (Excel/CSV/Parquet)
│  └─ figures/                # Gráficos, si los hay
│
├─ pyproject.toml             # Dependencias del proyecto
└─ README.md
```

---

## Trabajar con rutas

En vez de escribir rutas relativas a mano, importá las funciones ya armadas de `utils.py` — así los notebooks funcionan sin importar desde dónde se ejecuten:

```python
from uruguay_dua_comex import utils

df = pl.read_parquet(utils.data_processed_dir("dua_2016-2026_decoded.parquet"))
```

Disponibles: `project_dir`, `data_dir`, `data_raw_dir`, `data_interim_dir`, `data_processed_dir`, `outputs_dir`, `outputs_figures_dir`, `outputs_tables_dir`, `assets_dir`.

---

## Fuente de los datos

Declaraciones Únicas Aduaneras (DUA), publicadas por la Dirección Nacional de Aduanas de Uruguay en cumplimiento del artículo 43 de la Ley 19.438: https://www.aduanas.gub.uy — consultado por última vez el 2026-09-22.

---

## Licencia

Este proyecto se distribuye bajo licencia [MIT](/LICENSE).
