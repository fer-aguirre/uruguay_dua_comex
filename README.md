# Uruguay DUA Comex

Importaciones, exportaciones y tránsitos de Uruguay, a partir de las declaraciones aduaneras (DUA) que publica la Dirección Nacional de Aduanas (DNA), en una sola tabla limpia y fácil de consultar.

Creado por: Fernanda Aguirre Ruiz

---

## ¿Qué es esto?

La DNA publica a diario, por ley (Ley 19.438, art. 43), el detalle de todas las declaraciones aduaneras de Uruguay: qué se importó, exportó o pasó en tránsito, quién lo declaró, por qué valor, desde o hacia qué país, etc. Esos archivos son difíciles de usar tal como vienen:

- Se publican en XML, con un archivo por mes (y otro por día) en un servidor FTP.
- Usan nombres de columna internos (`DDPAIS_ORIGE`, `DDVAD_INCR`...) y códigos en vez de nombres.
- Cada mes trae tres archivos: declaraciones **ingresadas**, **modificadas** y **anuladas**. Para saber cuál es la versión vigente de cada declaración hay que combinarlos en orden.

Este proyecto toma esos archivos y arma **una sola tabla limpia**:

- **Desde enero de 2016**, con unas 20,5 millones de filas y 4,2 millones de declaraciones.
- **Una fila por ítem de declaración** (un producto dentro de una declaración).
- Con **la versión vigente de cada declaración**: se aplican las modificaciones y se excluyen las anuladas.
- Con **nombres de columna entendibles** y algunos códigos traducidos (ver [Diccionario de datos](#diccionario-de-datos)).
- **Actualizada todos los meses** de forma automática (ver [Actualización automática](#actualización-automática)).

> Solo incluye **meses cerrados**: el mes en curso nunca está, porque la DNA reescribe su archivo todos los días hasta que termina.

---

## Por dónde empezar

**Si querés buscar datos sin escribir código:**
Abrí [`notebooks/0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) en Jupyter o en tu editor de código, cambiá los valores de la celda de configuración (años, tipo de operación, nombre, código NCM, formato) y ejecutá todas las celdas. El resultado se muestra en el notebook y se guarda en `outputs/tables/`.

**Si preferís la terminal:**
```bash
uv run uruguay-dua-query --years 2024 --codigo 2701 --nombre "acme"
```
Más ejemplos en [Consultar los datos](#consultar-los-datos).

**Si vas a analizar los datos:**
Leé primero [Qué tener en cuenta al analizar](#qué-tener-en-cuenta-al-analizar) y el [diccionario de datos](#diccionario-de-datos).

**Si querés entender o modificar cómo se arma la tabla:**
Mirá [Cómo se arma la tabla](#cómo-se-arma-la-tabla) y [Actualización automática](#actualización-automática).

---

## Instalación

El proyecto usa [`uv`](https://docs.astral.sh/uv/), una herramienta que instala Python y todas las librerías necesarias en las versiones exactas del proyecto (definidas en `pyproject.toml` y `uv.lock`). Si todavía no la tenés, seguí su [guía de instalación](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/fer-aguirre/uruguay_dua_comex.git
cd uruguay_dua_comex
uv sync
```

`uv sync` crea una carpeta `.venv` con todo lo necesario, incluidos los comandos `uruguay-dua-query` (consultas) y `uruguay-dua-sync` (actualizar tus datos). Todos los comandos de este README se corren desde la carpeta del proyecto.

---

## Conseguir los datos

La tabla final es un único archivo, `dua_decoded.parquet` (~710 MB). Parquet es un formato de tabla comprimido, mucho más liviano y rápido que un CSV; se abre con Python (polars, pandas), R o DuckDB.

**No hace falta descargarla a mano.** La primera vez que corrés una consulta (con el notebook `0.3` o desde la terminal), si el archivo no está en `data/processed/`, se descarga solo desde el [release más reciente](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) del repositorio. Un *release* es una versión publicada del dataset en GitHub. Ahí también hay dos archivos más, que se bajan a mano:

- `dua_anulados.parquet`: la lista de declaraciones anuladas (año, número y mes de la anulación).
- `dua_historial.parquet` (~740 MB): todas las versiones de cada declaración, tal como aparecieron en cada archivo mensual. Sirve para ver qué cambió en una declaración modificada.

Si preferís armar la tabla desde cero, con los archivos originales de la DNA, seguí los pasos de [Cómo se arma la tabla](#cómo-se-arma-la-tabla).

### Actualizar tus datos

Los datos en GitHub se actualizan solos todos los meses, pero tu copia no. Para ponerla al día, corré estos dos comandos desde la carpeta del proyecto:

```bash
git pull
uv run uruguay-dua-sync
```

- `git pull` trae los últimos cambios del proyecto.
- `uruguay-dua-sync` compara tus archivos de `data/processed/` con los de GitHub y descarga solo los que estén viejos. Si ya están al día, no descarga nada. También actualiza `dua_anulados.parquet` y `dua_historial.parquet` si los tenés.

Si un archivo tuyo es distinto y más nuevo que el de GitHub (por ejemplo, porque lo armaste vos), no lo reemplaza: te avisa y lo deja como está.

En Windows, si el comando está bloqueado, usá `uv run python -m uruguay_dua_comex.sync`.

Hasta qué mes llega cada versión figura en las notas del [release más reciente](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) y en [`data/manifest.json`](data/manifest.json).

---

## Consultar los datos

Las consultas funcionan igual desde un notebook o desde la terminal. Hay que indicar al menos un **nombre** de importador o exportador o un **código NCM**, para no recorrer las 20 millones de filas sin acotar. Desde Python, los filtros se pasan a `Consulta`, que se usa tanto para consultar como para exportar: así el nombre del archivo siempre describe los datos que contiene.

| Filtro | Qué es | Ejemplo |
|---|---|---|
| `years` | Año o lista de años de presentación de la declaración | `2024` / `[2023, 2024, 2025]` |
| `tipo_regimen` *(opcional)* | Importación (`i`), exportación (`e`) o tránsito (`t`). Si no lo indicás, incluye los tres. | `"i"` / `["i", "e"]` |
| `nombre` *(opcional)* | Nombre del importador o exportador. Busca coincidencias parciales, sin distinguir mayúsculas de minúsculas; podés escribir puntos o paréntesis tal cual (ej. `"s.a."`). Cuanto más específico, mejor: un término corto puede devolver miles de resultados. | `"acme"` |
| `codigo` *(opcional)* | Código NCM (el código del producto en el Mercosur), completo o solo el comienzo. Los puntos son opcionales: `78.01` = `7801`. | `"2701"` |

**Desde un notebook:**
```python
from uruguay_dua_comex import Consulta, export_query_result, query_data, utils

consulta = Consulta(years=[2024, 2025], tipo_regimen="i", codigo="2701")
resultado = query_data(consulta)
export_query_result(
    resultado, consulta, output_dir=utils.outputs_tables_dir(), formato="xlsx"
)
```

**Desde la terminal:**
```bash
uv run uruguay-dua-query --years 2024 2025 -r i -c 2701 -f xlsx
uv run uruguay-dua-query --years 2023 2024 -n "acme" -o outputs/tables
```
Por defecto guarda un CSV en la carpeta donde estás parado/a. Con `-o` elegís otra carpeta (se crea si no existe) y con `-f` el formato: `csv`, `xlsx` o `parquet`. Todas las opciones aparecen con `--help`.

**Nombre del archivo:** se arma con la búsqueda y la fecha y hora de exportación, así nunca pisa un resultado anterior. Por ejemplo, `uy_importacion_acme_2701_2023-2024_20261111T153012.csv`: país, régimen (si no lo indicás, los tres: `exportacion-importacion-transito`), nombre, códigos NCM, años y fecha y hora en formato ISO 8601 (`AAAAMMDDTHHMMSS`). Los años seguidos se escriben como rango y los sueltos se suman con `+` (`2019-2021+2024`). Los acentos y los caracteres que no sirven en un nombre de archivo se reemplazan, el nombre se recorta a 40 caracteres y se escriben hasta 3 códigos (`0101-0102-0103-y5mas`).

El resultado trae las columnas del [diccionario de datos](#diccionario-de-datos), más `AÑO` (igual a `ANIO_PRESENTACION`) y `MES` (el mes de `FECHA_DUA`) para filtrar o agrupar más fácil.

> **¿CSV o Excel?** El CSV es el formato por defecto porque no tiene límite de filas. Excel admite como máximo 1.048.576 filas por hoja, así que una búsqueda amplia (por ejemplo, un capítulo NCM entero en varios años) puede no entrar en un `.xlsx`.

> **En Windows**, si `uv run uruguay-dua-query` falla con un error de que una directiva bloqueó el archivo, usá: `uv run python -m uruguay_dua_comex --years 2024 --codigo 2701`.

### Analizar la tabla completa

Para análisis que van más allá de un filtro (agregados por país, series de tiempo, etc.), podés leer la tabla directamente en tu propio notebook. Con [polars](https://docs.pola.rs/) y `scan_parquet`, la consulta solo lee las columnas y filas que necesita. `utils` arma las rutas a las carpetas del proyecto, así el código funciona desde cualquier notebook:

```python
import polars as pl

from uruguay_dua_comex import utils

# Valor en aduana importado en 2024 por país de origen (código y nombre de la DNA).
df_por_pais = (
    pl.scan_parquet(utils.data_processed_dir("dua_decoded.parquet"))
    .filter(
        pl.col("ANIO_PRESENTACION") == 2024,
        pl.col("TIPO_REGIMEN") == "Importación",
    )
    .group_by("PAIS_ORIGEN", "PAIS_ORIGEN_NOMBRE")
    .agg(pl.col("VALOR_ADUANA").sum())
    .sort("VALOR_ADUANA", descending=True)
    .collect()
)
```

---

## Qué tener en cuenta al analizar

- **Una fila es un ítem, no una declaración.** Una declaración que incluye cinco productos distintos aparece en cinco filas. Una declaración se identifica con **año + número** (`ANIO_PRESENTACION` + `NUMERO_PUBLICO_DUA`): el número se repite cada año.
- **Importaciones, exportaciones y tránsitos están mezclados.** Filtrá siempre por `TIPO_REGIMEN`. Los tránsitos son mercadería que pasa por Uruguay sin quedarse, no comercio de Uruguay, y pesan mucho: en 2024 suman un valor en aduana de 11.900 millones, casi lo mismo que las importaciones (12.600 millones).
- **Los montos se pueden sumar fila por fila.** `VALOR_ADUANA` y los impuestos son del ítem, no de la declaración. La especificación de la DNA no indica la moneda de `VALOR_ADUANA`; los impuestos están en dólares, y la relación entre el IVA y el valor en aduana indica que también lo está.
- **Los códigos se mantienen, y al lado va su nombre oficial.** Países, aduanas, vía de transporte, tipo de documento, régimen y subrégimen tienen una columna `_NOMBRE` con el nombre tal como lo escribe la DNA en sus tablas de codificación (por ejemplo, `PAIS_ORIGEN` `156` y `PAIS_ORIGEN_NOMBRE` `CHINA, REPUBLICA POPULAR DE`). Si la DNA cambió el nombre de un país, se usa el más reciente. Un código que no figura en las tablas oficiales queda con el nombre vacío: `PAIS_ORIGEN` `000` (350 filas de importación, 2016–2018) y cinco subregímenes (1.187 filas). Convenios, exoneraciones y unidades siguen solo como código, porque la DNA no publica esas tablas. Ver el [diccionario](#diccionario-de-datos).
- **Las exportaciones no son las cifras oficiales de exportación.** Los totales de la tabla quedan entre 14% y 19% por debajo de los de [Uruguay XXI](https://www.uruguayxxi.gub.uy/es/centro-informacion/articulo/exportaciones-de-bienes-con-zonas-francas/), por dos diferencias de cobertura:
  - **Incluyen los envíos a zonas francas uruguayas**, que Uruguay XXI no cuenta como exportación. Aparecen con una zona franca como destino (`PAIS_PROCEDENCIA_DESTINO` entre `980` y `997`, salvo `984`), sobre todo madera hacia las plantas de celulosa.
  - **No incluyen lo que se exporta desde zonas francas** (celulosa, concentrado de bebidas, farmacéuticos), porque esas ventas no se declaran con un DUA.

  Ajustando por las dos, la diferencia con Uruguay XXI queda por debajo de 1% en casi todos los años (ver [`0.4-validate-exports.ipynb`](notebooks/0.4-validate-exports.ipynb)).
- **En exportaciones, `VALOR_ADUANA` es el valor FOB en dólares.** Coincide con el FOB de Uruguay XXI en el 98% de las combinaciones de mes y producto. Los impuestos y sus porcentajes valen siempre 0 en exportaciones.
- **Algunas exportaciones tienen valor 0.** Son unas 20.400 filas, casi todas también con peso neto 0, sobre todo menudencias y carne. No afectan los totales.
- **Las anuladas no están en la tabla.** Una declaración anulada no cuenta como operación, así que se excluye. La lista está en `dua_anulados.parquet` (11.943 anulaciones).
- **Cada declaración aparece en su última versión.** Si una declaración se modificó, la tabla muestra solo los ítems de la versión más reciente. Las versiones anteriores están en `dua_historial.parquet`.
- **Las modificaciones y anulaciones se publican desde 2020.** Antes de 2020, la DNA publica esos archivos vacíos. Por eso, las declaraciones de 2016 a 2019 están como se ingresaron, salvo los cambios hechos desde 2020 en adelante.
- **Algunas columnas solo existen en ciertos años.** `REGIMEN_ADUANERO` y `SUBREGIMEN` existen desde 2020; `DDUNID_TRANS`, solo hasta 2019. En los otros años quedan vacías.
- **Los años se filtran por año de presentación.** La consulta usa `ANIO_PRESENTACION`. Para series mensuales, usá `FECHA_DUA`, la fecha de la declaración.
- **La DNA puede volver a publicar meses viejos.** A veces sube de nuevo archivos de meses ya cerrados; la tabla siempre refleja la última versión, y [`data/manifest.json`](data/manifest.json) registra cada reemplazo (ver [Actualización automática](#actualización-automática)).

---

## Diccionario de datos

Columnas de `dua_decoded.parquet`. Las descripciones vienen de la especificación de la DNA ([`docs/FormatoDUADiariosPublicos.htm`](docs/FormatoDUADiariosPublicos.htm)). La columna "¿Traducido?" indica si la columna tiene un nombre en vez de un código; solo se tradujo lo que figura en una fuente oficial de la DNA. Las columnas `_NOMBRE` vienen de las tablas de codificación de la DNA y van al lado de su código. El detalle de cada decisión, con sus fuentes, está en [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb).

| Columna | Tipo | ¿Traducido? | Descripción |
|---|---|---|---|
| ANIO_PRESENTACION | número | — | Año de presentación de la declaración |
| NUMERO_PUBLICO_DUA | texto | — | Número público de la declaración (se repite cada año) |
| FECHA_DUA | fecha | — | Fecha de la declaración |
| TIPO_REGIMEN | texto | Sí | Importación, Exportación o Tránsito |
| PAIS_ORIGEN | texto | No | País de origen (código) |
| PAIS_ORIGEN_NOMBRE | texto | Sí | Nombre del país de origen, según la DNA |
| NCM | texto | No | Nomenclatura Común del Mercosur, 10 dígitos |
| PAIS_PROCEDENCIA_DESTINO | texto | No | País de procedencia (importación) o de destino (exportación) (código). Incluye las zonas francas uruguayas (`980`–`997`) |
| PAIS_PROCEDENCIA_DESTINO_NOMBRE | texto | Sí | Nombre del país o zona franca de procedencia o destino, según la DNA |
| CONVENIO_INTERNACIONAL | texto | No | Acuerdo comercial aplicado (código) |
| CODIGO_EXONERACION | texto | No | Exoneración aplicada (código) |
| CANTIDAD_UNIDADES_COMERCIALES | número | — | Cantidad en unidades comerciales |
| TIPO_UNIDAD_COMERCIAL | texto | No | Tipo de unidad comercial (código) |
| CANTIDAD_UNIDADES_FISICAS | número | — | Cantidad en unidades físicas |
| TIPO_UNIDAD_FISICA | texto | No | Tipo de unidad física (código) |
| VALOR_ADUANA | número | — | Valor en aduana del ítem |
| IMADUNI_USD, IMADUNI_LIBERADO_USD | número | — | Impuesto Aduanero Único a la Importación, pagado y liberado, en USD |
| RECARGO_MINIMO_USD, RECARGO_MINIMO_LIBERADO_USD | número | — | Recargo mínimo, pagado y liberado, en USD |
| RECARGO_ADICIONAL_USD, RECARGO_ADICIONAL_LIBERADO_USD | número | — | Recargo adicional, pagado y liberado, en USD |
| RECARGO_MOVIL_USD, RECARGO_MOVIL_LIBERADO_USD | número | — | Recargo móvil, pagado y liberado, en USD |
| IVA_USD, IVA_LIBERADO_USD | número | — | IVA, pagado y liberado, en USD |
| IVA_ANTICIPO_USD, IVA_ANTICIPO_LIBERADO_USD | número | — | Anticipo de IVA, pagado y liberado, en USD |
| IMADUNI_PORCENTAJE, RECARGO_MINIMO_PORCENTAJE, RECARGO_ADICIONAL_PORCENTAJE, IVA_PORCENTAJE, IVA_ANTICIPO_PORCENTAJE | número | — | Tasa de cada impuesto, en porcentaje |
| VIA_TRANSPORTE | texto | No | Vía de transporte (código) |
| VIA_TRANSPORTE_NOMBRE | texto | Sí | Nombre de la vía de transporte, según la DNA |
| DDUNID_TRANS | texto | No | Campo publicado solo hasta 2019 y sin documentar; queda con su nombre original |
| ADUANA_INGRESO_EGRESO | texto | No | Aduana de ingreso o egreso (código) |
| ADUANA_INGRESO_EGRESO_NOMBRE | texto | Sí | Nombre de la aduana, según la DNA |
| TIPO_DOCUMENTO_IMPOEXPO | texto | No | Tipo de documento del importador o exportador (código) |
| TIPO_DOCUMENTO_IMPOEXPO_NOMBRE | texto | Sí | Nombre del tipo de documento, según la DNA |
| NUMERO_DOCUMENTO_IMPOEXPO | texto | — | Documento del importador o exportador (RUT, CI, etc.) |
| PESO_BRUTO | número | — | Peso bruto |
| PESO_NETO | número | — | Peso neto |
| NOMBRE_IMPORTADOR_EXPORTADOR | texto | — | Nombre del importador o exportador |
| REGIMEN_ADUANERO | texto | No | Régimen aduanero (código, desde 2020) |
| REGIMEN_ADUANERO_NOMBRE | texto | Sí | Nombre del régimen aduanero, según la DNA |
| SUBREGIMEN | texto | No | Subrégimen (código, desde 2020). El mismo código puede significar cosas distintas en regímenes distintos |
| SUBREGIMEN_NOMBRE | texto | Sí | Nombre del subrégimen dentro de su régimen, según la DNA |
| FUENTE_PERIODO | número | — | Mes (AAAAMM) del archivo de donde sale la versión vigente de la declaración |
| FUENTE_TIPO | texto | — | Archivo de donde sale esa versión: `ing` (ingresada) o `mod` (modificada) |

> **Para verificar un código a mano:** La herramienta [Consultas DUA](https://www.aduanas.gub.uy/innovaportal/v/18714/6/innova.front/consultas-dua.html) permite filtrar por estos mismos campos.

---

## Cómo se arma la tabla

El proceso está dividido en notebooks numerados que se corren en orden: cada uno usa los archivos que deja el anterior. Cada paso saltea lo que ya hizo, así que volver a correrlos solo procesa lo que cambió. Cada notebook explica en su primera celda qué hace y por qué.

| Notebook | Qué hace | Entrada | Salida |
|---|---|---|---|
| [`0.0-collect-data.ipynb`](notebooks/0.0-collect-data.ipynb) | Descarga del FTP de la DNA los archivos mensuales de los meses cerrados que falten o hayan cambiado, y sus tablas de codificación de países, aduanas y vías de transporte. Si un archivo cambió, guarda la versión nueva al lado de la anterior, sin borrarla. | FTP de la DNA | `data/raw/<año>/dmAAAAMM.zip` y `data/raw/catalogos/` |
| [`0.1-convert-parquet.ipynb`](notebooks/0.1-convert-parquet.ipynb) | Convierte cada archivo mensual, junta todas las versiones de cada declaración en un historial y arma la tabla con la versión vigente de cada una. | `data/raw/<año>/*.zip` | `data/processed/dua_historial.parquet`, `dua.parquet` y `dua_anulados.parquet` |
| [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb) | Pone nombres entendibles a las columnas y agrega el nombre oficial de cada código que figura en las tablas de la DNA. | `dua.parquet` y `data/raw/catalogos/` | `dua_decoded.parquet` |
| [`0.3-query-data.ipynb`](notebooks/0.3-query-data.ipynb) | Consulta la tabla final y exporta el resultado. | `dua_decoded.parquet` | CSV, Excel o parquet en `outputs/tables/` |
| [`0.4-validate-exports.ipynb`](notebooks/0.4-validate-exports.ipynb) | Compara las exportaciones de la tabla con la serie oficial de Uruguay XXI, año por año, y explica la diferencia. No es parte del armado de la tabla. | `dua_decoded.parquet` y la serie de Uruguay XXI (se descarga sola) | Tablas en el notebook |

El código de cada paso está en [`uruguay_dua_comex/pipeline.py`](uruguay_dua_comex/pipeline.py), el mismo que usa la actualización automática.

> **Sobre el FTP de la DNA:** es público y de acceso anónimo (`ftp.aduanas.gub.uy`, carpetas `DUA Diarios XML` y `Datos Basicos`; ver [`docs/configuracion-cliente-ftp.pdf`](docs/configuracion-cliente-ftp.pdf)). Desde algunas redes la conexión se corta por tiempo; en ese caso, un programa de FTP como WinSCP puede servir para descargar los archivos a mano.

---

## Actualización automática

La DNA cierra el archivo de cada mes el último día del mes o el 1 del mes siguiente. Un proceso automático en GitHub (un *workflow* de GitHub Actions, definido en [`.github/workflows/update-data.yml`](.github/workflows/update-data.yml)) revisa **del 1 al 7 de cada mes, a las 09:14 (hora de Uruguay)**, el tamaño y la fecha de cada archivo mensual en el FTP. Si algún mes es nuevo o cambió:

1. Descarga y convierte **solo esos meses**, y descarga de nuevo las tablas de codificación de la DNA si cambiaron (la DNA a veces cambia el nombre de un país).
2. Reconstruye la tabla final a partir del historial (hace falta porque una modificación o anulación puede afectar a declaraciones de meses anteriores) y publica un [release](https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest) nuevo, con la fecha de la actualización como nombre (ej. `v2026.11.02`). Solo se conserva el release más reciente.
3. Anota los meses procesados en [`data/manifest.json`](data/manifest.json), el registro de meses procesados. Para cada mes guarda el tamaño y la fecha del archivo en el FTP, cuántas filas trajo (ingresadas, modificadas y anuladas) y cuándo se procesó.

**Si la DNA vuelve a publicar un mes ya procesado**, la versión anterior queda anotada en el manifest, dentro de `previous`, con la fecha en que se reemplazó. Comparando la cantidad de filas de las dos versiones se puede ver si cambiaron los datos o si solo se regeneró el archivo.

Si no hay nada nuevo, termina en un par de minutos sin cambiar nada. También se puede correr a mano desde la pestaña **Actions** del repositorio (botón *Run workflow*) o, en tu computadora, con `uv run uruguay-dua-update`.

---

## Estructura del proyecto

```
uruguay_dua_comex/
├─ uruguay_dua_comex/         # Código del proyecto
│  ├─ query.py                # Consultas y exportación (notebook y terminal)
│  ├─ sync.py                 # Pone al día los datos locales con el release
│  ├─ consulta.py             # Parámetros de la búsqueda y nombre del archivo exportado
│  ├─ pipeline.py             # Pasos para armar la tabla
│  ├─ update.py               # Actualización con los meses nuevos o modificados
│  ├─ utils.py                # Rutas a las carpetas del proyecto
│  └─ __main__.py             # Permite consultar con `python -m uruguay_dua_comex`
│
├─ notebooks/                 # Los pasos del proceso, numerados
│  ├─ 0.0-collect-data.ipynb
│  ├─ 0.1-convert-parquet.ipynb
│  ├─ 0.2-decode-data.ipynb
│  ├─ 0.3-query-data.ipynb
│  └─ 0.4-validate-exports.ipynb   # Comparación con Uruguay XXI
│
├─ data/
│  ├─ raw/                    # Archivos originales: de la DNA por año, sus tablas de codificación (catalogos/) y la serie de Uruguay XXI
│  ├─ interim/                # Archivos intermedios, por mes
│  ├─ processed/              # Historial y tablas finales, listas para consultar
│  └─ manifest.json           # Registro de meses procesados
│
├─ docs/
│  ├─ FormatoDUADiariosPublicos.htm   # Especificación de los archivos de la DNA
│  ├─ codificacion-campos-dua-2025.pdf   # Códigos de los campos del DUA, según la DNA
│  ├─ configuracion-cliente-ftp.pdf   # Guía de la DNA para acceder a su FTP
│  └─ dua_transito.pdf                # Diagrama del trámite del DUA de tránsito
│
├─ .github/workflows/         # Actualización automática mensual
├─ outputs/tables/            # Resultados de las consultas
├─ pyproject.toml             # Librerías del proyecto
└─ README.md
```

---

## Fuentes

- Declaraciones Únicas Aduaneras (DUA), Dirección Nacional de Aduanas de Uruguay, publicadas en su FTP público: `ftp://ftp.aduanas.gub.uy/DUA Diarios XML/` ([información del sitio FTP](https://www.aduanas.gub.uy/innovaportal/v/14679/4/innova.front/sitio-ftp.html)). Consultado por última vez el 2026-10-09.
- Ley 19.438, art. 43: https://www.impo.com.uy/bases/leyes/19438-2016/43
- Especificación de los archivos: [`docs/FormatoDUADiariosPublicos.htm`](docs/FormatoDUADiariosPublicos.htm)
- Tablas de codificación de la DNA (países, aduanas y vías de transporte), en el mismo FTP: `ftp://ftp.aduanas.gub.uy/Datos Basicos/` (`rgpais.zip`, `rgaduan.zip`, `dbviatr.zip`). Consultadas por última vez el 2026-11-05.
- Codificación de los campos del DUA (tipo de documento, régimen y subrégimen), anexo de la DNA al expediente 2025-5-1-0004266 del Ministerio de Economía y Finanzas (resolución del 2025-06-26): [`docs/codificacion-campos-dua-2025.pdf`](docs/codificacion-campos-dua-2025.pdf), descargado el 2026-11-05 de https://www.aduanas.gub.uy/innovaportal/file/27289/1/expediente-2025-5-1-0004266-diego-tenenbaum-lion.pdf
- Fuentes de cada código traducido: primera celda de [`0.2-decode-data.ipynb`](notebooks/0.2-decode-data.ipynb)
- Exportaciones de bienes con zonas francas, Uruguay XXI (para la validación de exportaciones): https://www.uruguayxxi.gub.uy/es/centro-informacion/articulo/exportaciones-de-bienes-con-zonas-francas/. Versión publicada el 2026-11-04, descargada el 2026-11-05.

---

## Licencia

Este proyecto se distribuye bajo licencia [MIT](LICENSE).

---

Este repositorio fue generado con [cookiecutter](https://github.com/fer-aguirre/cookiecutter-data-analysis-lite).
