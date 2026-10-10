# Uruguay DUA Comex

Datos de comercio exterior de Uruguay (importaciones, exportaciones y tránsitos), a partir de las declaraciones aduaneras (DUA) que publica la Dirección Nacional de Aduanas (DNA), en un formato limpio y fácil de consultar.

Creado por: Fernanda Aguirre Ruiz

---

## ¿Qué es esto?

La DNA publica a diario, por ley, el detalle de todas las declaraciones aduaneras de Uruguay (Ley 19.438, art. 43): qué se importó o exportó, con quién, por qué monto, desde/hacia qué país, etc. Ese archivo crudo es difícil de usar directamente (viene en XML, con códigos internos, sin unificar meses ni corregir declaraciones modificadas o anuladas).

Este proyecto toma esos archivos crudos y arma **una sola tabla limpia** (desde enero 2016, solo meses cerrados), con nombres de columna entendibles en vez de códigos, lista para explorar sin necesidad de saber programar para usarla.

La tabla se actualiza sola: todos los meses, un proceso automático revisa si la DNA publicó meses nuevos o modificó alguno anterior y, si es así, procesa solo esos meses y publica la versión actualizada. Ver [Actualización automática](#actualización-automática).

---

## Por dónde empezar

**Si solo querés buscar datos (sin programar):**
Abrí [`notebooks/0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) en Jupyter, cambiá los valores de la celda de configuración (años, nombre de empresa, código NCM) y ejecutá. Te deja el resultado también exportado en Excel/CSV en `outputs/tables/`.

**Si preferís la terminal:**
```bash
uv run python -m uruguay_dua_comex.query --years 2024 --ncm 2701 --nombre "acme"
```
Ver todas las opciones con `--help`. Más ejemplos en [Consultar los datos](#consultar-los-datos) más abajo.

**Si querés entender o modificar cómo se arma el dataset:**
Mirá [El pipeline de datos](#el-pipeline-de-datos): son notebooks numerados que se corren en orden.

---

## Instalación

Este proyecto usa [`uv`](https://docs.astral.sh/uv/) para manejar Python y las dependencias (ya viene todo definido en `pyproject.toml`/`uv.lock`, no hay que instalar nada a mano).

```bash
git clone https://github.com/fer-aguirre/uruguay_dua_comex.git
cd uruguay_dua_comex
uv sync
```

Eso crea un entorno virtual (`.venv`) con todo lo necesario.

---

## Conseguir los datos

La tabla final (`dua_decoded.parquet`, ~700 MB) se descarga sola la primera vez que hace falta — no hay que hacer nada a mano. En cuanto corrés una consulta (notebook `0.3` o la CLI) y el archivo todavía no está en `data/processed/`, se baja automáticamente desde el [release más reciente](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) del repositorio (con barra de progreso), y queda guardado ahí para las próximas veces.

El release también incluye `dua_anulados.parquet` (la lista de declaraciones anuladas) y `dua_historial.parquet` (todas las versiones de cada declaración, tal como aparecieron en cada archivo mensual); se pueden bajar a mano desde la página del release.

Si en cambio querés armar la tabla por tu cuenta desde cero, corré los notebooks del [pipeline](#el-pipeline-de-datos) en orden, empezando por `0.0`, que descarga los archivos mensuales del FTP público de la DNA (`ftp.aduanas.gub.uy`, carpeta `DUA Diarios XML`, acceso anónimo; ver [`docs/configuracion-cliente-ftp.pdf`](docs/configuracion-cliente-ftp.pdf)). Ojo: algunas redes no pueden descargar de ese servidor (la conexión se corta por tiempo); en ese caso, un cliente FTP como WinSCP puede servir.

> **Para tener los meses más recientes:** si ya descargaste la tabla antes, tu copia no se actualiza sola, porque el archivo local ya existe. Borrá `data/processed/dua_decoded.parquet` y volvé a correr una consulta: se descarga la versión más nueva. Podés ver hasta qué mes llega cada versión en las notas del [release más reciente](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) o en [`data/manifest.json`](data/manifest.json).

---

## El pipeline de datos

Notebooks pensados para correrse en orden (cada uno depende de los archivos que arma el anterior). La lógica vive en [`uruguay_dua_comex/pipeline.py`](uruguay_dua_comex/pipeline.py), la misma que usa la [actualización automática](#actualización-automática); cada paso saltea lo que ya hizo, así que volver a correrlos solo procesa lo que cambió.

| Notebook | Qué hace | Entrada | Salida |
|---|---|---|---|
| [`0.0-collect-data.ipynb`](notebooks/0.0-collect-data.ipynb) | Descarga del FTP de la DNA los archivos mensuales de los meses cerrados que falten o hayan cambiado. Nunca sobrescribe un archivo ya descargado: una versión nueva se guarda al lado. | FTP de la DNA | `data/raw/<año>/dmAAAAMM.zip` |
| [`0.1-convert-parquet.ipynb`](notebooks/0.1-convert-parquet.ipynb) | Convierte cada archivo mensual, junta todas las versiones de cada declaración en un historial y arma la tabla final, aplicando altas, modificaciones y anulaciones en el orden correcto. | `data/raw/<año>/*.zip` | `data/processed/dua_historial.parquet`, `dua.parquet` y `dua_anulados.parquet` |
| [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb) | Traduce los códigos internos de la DNA que se pueden verificar contra una fuente oficial (ej. tipo de régimen, tipo de documento) y renombra todas las columnas a nombres entendibles. | `dua.parquet` | `dua_decoded.parquet` |
| [`0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) | Consulta el dataset final por año, régimen, empresa y/o NCM, y exporta el resultado. | `dua_decoded.parquet` | Excel/CSV/Parquet en `outputs/tables/` |

Cada notebook explica en su primera celda, en detalle, las reglas y fuentes oficiales detrás de sus decisiones (por ejemplo, qué códigos se pudieron traducir con certeza y cuáles no).

---

## Actualización automática

La DNA cierra el archivo de cada mes el último día del mes o el 1 del mes siguiente. Un workflow de GitHub Actions ([`.github/workflows/update-data.yml`](.github/workflows/update-data.yml)) revisa del **1 al 7 de cada mes a las 09:14 (hora de Uruguay)** el tamaño y la fecha de cada archivo mensual en el FTP y, si algún mes cerrado es nuevo o cambió:

1. Descarga y convierte **solo esos meses**.
2. Reconstruye la tabla final a partir del historial (hace falta, porque las modificaciones y anulaciones de un mes pueden afectar declaraciones de meses anteriores) y publica un [release](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) nuevo, con la fecha de la actualización como nombre (ej. `v2026.11.02`). Se conserva solo el release más reciente.
3. Registra los meses procesados en [`data/manifest.json`](data/manifest.json), con el tamaño y la fecha de cada archivo en el FTP, la cantidad de filas de sus archivos Ing, Mod y Anu, y la fecha en que se procesó. Si la DNA vuelve a subir un mes ya procesado, la versión reemplazada queda en `previous`, con la fecha en que se reemplazó: comparando las filas se ve si cambiaron los datos o solo se regeneró el archivo.

El mes en curso nunca se incluye: la DNA lo reescribe todos los días hasta que termina. Si no hay cambios, termina en un par de minutos sin publicar nada. También se puede correr a mano desde la pestaña **Actions** del repositorio (botón *Run workflow*), o en local con `uv run python -m uruguay_dua_comex.update`.

---

## Consultar los datos

La lógica de consulta vive en [`uruguay_dua_comex/query.py`](uruguay_dua_comex/query.py) y funciona igual desde un notebook o desde la terminal.

**Filtros disponibles** (al menos `nombre` o `ncm` es obligatorio, para no escanear las ~20 millones de filas sin acotar):

| Filtro | Qué es | Ejemplo |
|---|---|---|
| `years` | Año o lista de años | `2024` / `[2023, 2024, 2025]` |
| `tipo_regimen` *(opcional)* | Importación (`i`), Exportación (`e`) o Tránsito (`t`) | `"i"` / `["i", "e"]` |
| `nombre` *(opcional)* | Nombre del importador/exportador. Busca coincidencia parcial, sin distinguir mayúsculas/minúsculas; podés escribir puntos o paréntesis tal cual (ej. `"s.a."`). Cuanto más específico, mejor: un término corto puede devolver miles de resultados. | `"acme"` |
| `ncm` *(opcional)* | Código NCM o prefijo. Los puntos son opcionales: `78.01` = `7801`, y `7801.10.00` = `7801100000`. | `"2701"` |

**Desde un notebook:**
```python
from uruguay_dua_comex.query import query_dua, export_query_result

resultado = query_dua(years=[2024, 2025], tipo_regimen="i", ncm="2701")
export_query_result(resultado, [2024, 2025], "i", None, "2701", formato="xlsx")
```

**Desde la terminal:**
```bash
uv run python -m uruguay_dua_comex.query --years 2024 2025 -r i -n 2701 -f xlsx
```
Por defecto exporta un CSV al directorio donde estás parado/a; usá `--output`/`-o` para elegir otra carpeta (se crea si no existe) y `--formato`/`-f` para elegir entre `csv`, `xlsx` o `parquet`. Ver todas las opciones con `--help`.

> **¿CSV o Excel?** El CSV es el formato por defecto porque no tiene límite de filas. Excel admite como máximo 1.048.576 filas por hoja, así que una búsqueda amplia (por ejemplo, un capítulo NCM entero en varios años) puede no entrar en un `.xlsx`.

---

## Diccionario de datos

La especificación oficial de la DNA para estos archivos está en [`docs/FormatoDUADiariosPublicos.htm`](docs/FormatoDUADiariosPublicos.htm). La tabla completa de qué significa cada columna del dataset final (nombre original de la DNA, nombre nuevo, y si su código fue traducido o no, con la fuente oficial de cada decisión) está en la primera celda de [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb).

---

## Estructura del proyecto

```
uruguay_dua_comex/
├─ uruguay_dua_comex/         # Paquete de Python del proyecto
│  ├─ utils.py                # Rutas a las carpetas del proyecto (data_raw_dir, etc.)
│  ├─ query.py                # Consulta y exportación del dataset (librería + CLI)
│  ├─ pipeline.py             # Pasos del pipeline (los usan los notebooks y la actualización)
│  └─ update.py               # Actualización con los meses nuevos o modificados
│
├─ notebooks/                 # El pipeline, en pasos numerados (ver más arriba)
│  ├─ 0.0-collect-data.ipynb
│  ├─ 0.1-convert-parquet.ipynb
│  ├─ 0.2-decode-data.ipynb
│  └─ 0.3-query-data.ipynb
│
├─ data/
│  ├─ raw/                    # Archivos originales de la DNA, sin tocar
│  ├─ interim/                # Archivos intermedios de 0.1 (uno por mes)
│  ├─ processed/              # Historial y tablas finales, listas para consultar
│  └─ manifest.json           # Meses procesados (lo actualiza el workflow)
│
├─ docs/
│  ├─ FormatoDUADiariosPublicos.htm   # Especificación oficial de la DNA
│  └─ configuracion-cliente-ftp.pdf   # Guía de la DNA para acceder a su FTP
│
├─ .github/workflows/
│  └─ update-data.yml         # Actualización automática mensual
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

df = pl.read_parquet(utils.data_processed_dir("dua_decoded.parquet"))
```

Disponibles: `project_dir`, `data_dir`, `data_raw_dir`, `data_interim_dir`, `data_processed_dir`, `outputs_dir`, `outputs_figures_dir`, `outputs_tables_dir`, `assets_dir`.

---

## Fuente de los datos

Declaraciones Únicas Aduaneras (DUA), publicadas por la Dirección Nacional de Aduanas de Uruguay en cumplimiento del artículo 43 de la Ley 19.438, en su servidor FTP público: `ftp://ftp.aduanas.gub.uy/DUA Diarios XML/` (ver https://www.aduanas.gub.uy/innovaportal/v/14679/4/innova.front/sitio-ftp.html) — consultado por última vez el 2026-10-09.

---

## Licencia

Este proyecto se distribuye bajo licencia [MIT](/LICENSE).
