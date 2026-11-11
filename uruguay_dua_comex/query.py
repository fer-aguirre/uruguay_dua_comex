"""Consulta y exportación de declaraciones DUA decodificadas.

Funciona tanto como librería como CLI (`uruguay-dua-query`):

    from uruguay_dua_comex import Consulta, export_query_result, query_data

    consulta = Consulta(years=[2024, 2025], tipo_regimen="i", codigo="2701")
    df_result = query_data(consulta)
    export_query_result(df_result, consulta)

El archivo exportado es CSV por defecto (`formato`/--formato/-f también acepta
"xlsx" y "parquet") y va por defecto al directorio actual; usar
`output_dir`/--output/-o para exportarlo a otra carpeta (que se crea si no
existe). Los notebooks pasan `output_dir=utils.outputs_tables_dir()`. El
nombre del archivo lo arma `Consulta.export_filename` (ver `consulta.py`).

Si el dataset decodificado no existe en `data/processed/`, se descarga
automáticamente desde el release más reciente del repositorio en GitHub.
"""

import argparse
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import requests
from tqdm.auto import tqdm

from uruguay_dua_comex import utils
from uruguay_dua_comex.consulta import TIPO_REGIMEN_MAP, Consulta

logger = logging.getLogger(__name__)

# Nombre fijo del archivo tal como se sube a cada GitHub release: la URL de
# "latest" necesita un nombre de archivo conocido de antemano, así que no
# incluye el rango de fechas, que crece con cada actualización.
DECODED_FILENAME = "dua_decoded.parquet"
RELEASE_DOWNLOAD_URL = (
    "https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest/download/"
)

# Formatos de archivo aceptados para exportar el resultado de una consulta.
EXPORT_FORMATS = ("csv", "xlsx", "parquet")


def download_release_asset(filename: str) -> Path:
    """Download a file from the latest GitHub release into data/processed/.

    Downloads to a temporary file first and renames it into place only once
    complete, so an interrupted download never leaves a truncated file that
    looks like a valid cached file on the next run.

    Args:
        filename: Name of the file in the release (e.g. DECODED_FILENAME).

    Returns:
        Path to the downloaded file.
    """
    url = RELEASE_DOWNLOAD_URL + filename
    destination = utils.data_processed_dir(filename)
    logger.info("Descargando %s desde %s...", filename, url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + ".tmp")

    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    total = int(response.headers.get("content-length", 0))
    with (
        tmp_path.open("wb") as file_,
        tqdm(
            total=total, unit="B", unit_scale=True, desc=f"Descargando {filename}"
        ) as progress,
    ):
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            file_.write(chunk)
            progress.update(len(chunk))

    tmp_path.replace(destination)
    logger.info("Descarga completa: %s", destination)
    return destination


def _decoded_data_path() -> Path:
    """Locate the decoded DUA parquet, downloading it first if it's missing.

    Returns:
        Path to data/processed/dua_decoded.parquet. If it isn't there, it's
        downloaded first from the latest GitHub release.
    """
    path = utils.data_processed_dir(DECODED_FILENAME)
    if path.exists():
        return path
    return download_release_asset(DECODED_FILENAME)


def query_data(consulta: Consulta) -> pl.DataFrame:
    """Consulta el dataset de DUA decodificado.

    A diferencia del dataset de ARCA Comex, este incluye importaciones,
    exportaciones y tránsitos en la misma tabla, por lo que
    `consulta.tipo_regimen` permite acotar a uno o más de ellos.

    Agrega dos columnas, igual que en argentina_afip_comex: AÑO (igual a
    ANIO_PRESENTACION) y MES (el mes de FECHA_DUA).

    Args:
        consulta: Parámetros de la búsqueda (años, régimen, nombre y/o
            código NCM).

    Returns:
        DataFrame de polars con las filas que cumplen los filtros.
    """
    filters = [pl.col("ANIO_PRESENTACION").is_in(consulta.year_values)]

    if consulta.regimen_values:
        filters.append(
            pl.col("TIPO_REGIMEN").is_in(
                [TIPO_REGIMEN_MAP[code] for code in consulta.regimen_values]
            )
        )

    if consulta.nombre_value is not None:
        # Escapado para que caracteres como "." o "(" se busquen literalmente.
        filters.append(
            pl.col("NOMBRE_IMPORTADOR_EXPORTADOR").str.contains(
                f"(?i){re.escape(consulta.nombre_value)}"
            )
        )

    if consulta.codigo_values:
        # La columna NCM ya está solo con dígitos ("7801100000").
        codes = consulta.codigo_values
        ncm_filter = pl.col("NCM").str.starts_with(codes[0])
        for code in codes[1:]:
            ncm_filter = ncm_filter | pl.col("NCM").str.starts_with(code)
        filters.append(ncm_filter)

    combined_filter = filters[0]
    for extra_filter in filters[1:]:
        combined_filter = combined_filter & extra_filter

    return (
        pl.scan_parquet(_decoded_data_path())
        .filter(combined_filter)
        .with_columns(
            pl.col("ANIO_PRESENTACION").cast(pl.Int64).alias("AÑO"),
            pl.col("FECHA_DUA").dt.month().cast(pl.Int64).alias("MES"),
        )
        .collect()
    )


def export_query_result(
    df_result: pl.DataFrame,
    consulta: Consulta,
    output_dir: Path | None = None,
    formato: str = "csv",
) -> Path | None:
    """Exporta el resultado de una consulta a un archivo.

    El nombre del archivo se arma a partir de la consulta, con la fecha y
    hora de exportación, hasta segundos (ver `Consulta.export_filename`).

    Args:
        df_result: DataFrame a exportar, resultado de `query_data(consulta)`.
        consulta: La misma consulta usada para obtener `df_result`.
        output_dir: Carpeta donde escribir el archivo. Si es `None`, se usa
            el directorio actual. Se crea automáticamente si no existe.
        formato: Formato de exportación: "csv" (default), "xlsx" o
            "parquet". No distingue mayúsculas/minúsculas.

    Returns:
        La ruta del archivo generado, o None si no había filas para exportar.

    Raises:
        ValueError: Si `formato` no es uno de EXPORT_FORMATS.
    """
    formato = formato.lower()
    if formato not in EXPORT_FORMATS:
        raise ValueError(
            f"formato inválido: {formato!r}. Valores válidos: {EXPORT_FORMATS}."
        )

    if df_result.height == 0:
        logger.info("La consulta no devolvió filas. No se generó ningún archivo.")
        return None

    export_dir = output_dir if output_dir is not None else Path.cwd()
    if not export_dir.exists():
        logger.info("El directorio de salida no existe, se crea: %s", export_dir)
        export_dir.mkdir(parents=True)
    export_path = export_dir / consulta.export_filename(formato)

    logger.info("Exportando %d filas a: %s", df_result.height, export_path)
    if formato == "csv":
        df_result.write_csv(export_path)
    elif formato == "xlsx":
        df_result.write_excel(export_path)
    else:
        df_result.write_parquet(export_path)
    logger.info("Exportación completa.")
    return export_path


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de la CLI `uruguay-dua-query`.

    Returns:
        Parser de argparse configurado con las opciones de la consulta.
    """
    parser = argparse.ArgumentParser(
        prog="uruguay-dua-query",
        description=(
            "Consulta declaraciones DUA decodificadas por año, régimen, "
            "importador/exportador y/o código NCM, y exporta el resultado "
            "(CSV por defecto, o XLSX/Parquet con --formato) en el directorio "
            "actual, o en la carpeta indicada con --output. Debe indicarse "
            "--nombre y/o --codigo."
        ),
    )
    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        required=True,
        metavar="AÑO",
        help="Uno o más años a consultar, separados por espacios (ej. --years 2023 2024 2025).",
    )
    parser.add_argument(
        "-r",
        "--tipo-regimen",
        type=str.lower,
        nargs="+",
        default=None,
        choices=sorted(TIPO_REGIMEN_MAP),
        metavar="REGIMEN",
        help=(
            "Uno o más de: i (Importación), e (Exportación), t (Tránsito). "
            "No distingue mayúsculas/minúsculas. Por defecto incluye los tres."
        ),
    )
    parser.add_argument(
        "-n",
        "--nombre",
        type=str,
        default=None,
        help=(
            "Nombre (o parte del nombre) del importador/exportador a buscar "
            "(texto literal, no distingue mayúsculas/minúsculas). Cuanto más específico el "
            'nombre, mejor: un término corto como "sa" puede devolver miles '
            "de coincidencias distintas."
        ),
    )
    parser.add_argument(
        "-c",
        "--codigo",
        type=str,
        nargs="+",
        default=None,
        metavar="NCM",
        help=(
            "Uno o más códigos NCM (o prefijos) a buscar, separados por espacios "
            "(ej. --codigo 73 84.20). Los puntos son opcionales (78.01 y 7801 son "
            "equivalentes)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        metavar="RUTA",
        help=(
            "Carpeta donde escribir el archivo exportado. Por defecto es el "
            "directorio actual. Se crea automáticamente si no existe."
        ),
    )
    parser.add_argument(
        "-f",
        "--formato",
        type=str.lower,
        default="csv",
        choices=EXPORT_FORMATS,
        metavar="FORMATO",
        help="Formato de exportación: csv (default), xlsx o parquet. No distingue mayúsculas/minúsculas.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI `uruguay-dua-query`.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si la consulta se ejecutó
        correctamente. Si los argumentos son inválidos, argparse termina el
        proceso con código 2.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    try:
        consulta = Consulta(
            years=args.years,
            tipo_regimen=args.tipo_regimen,
            nombre=args.nombre,
            codigo=args.codigo,
        )
    except ValueError as error:
        parser.error(str(error))

    df_result = query_data(consulta)
    export_query_result(
        df_result, consulta, output_dir=args.output, formato=args.formato
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
