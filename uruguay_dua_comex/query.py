"""Consulta y exportación de declaraciones DUA decodificadas.

Funciona tanto como librería (`from uruguay_dua_comex.query import query_dua`)
como CLI (`python -m uruguay_dua_comex.query --years 2024 --ncm 2701`). El
archivo exportado es CSV por defecto (`formato`/--formato/-f también acepta
"xlsx" y "parquet") y va por defecto al directorio actual, tanto desde la
librería como desde la CLI; usar `output_dir`/--output/-o para exportarlo a
otra carpeta (que se crea si no existe). Los notebooks pasan explícitamente
`output_dir=utils.outputs_tables_dir()` para que sus exports sigan yendo a
`outputs/tables/`.

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

logger = logging.getLogger(__name__)

# Matches only 0.2-decode-data.ipynb's output, e.g. dua_2016-2026_decoded.parquet.
DECODED_PATTERN = re.compile(r"^dua_\d{4}-\d{4}_decoded\.parquet$")

# Nombre fijo del archivo tal como se sube a cada GitHub release: la URL de
# "latest" necesita un nombre de archivo conocido de antemano, así que el
# release siempre publica el dataset decodificado con este mismo nombre,
# aunque el rango de años real vaya creciendo con el tiempo.
DECODED_FILENAME = "dua_2016-2026_decoded.parquet"
RELEASE_DOWNLOAD_URL = (
    "https://github.com/fer-aguirre/uruguay_dua_comex/releases/latest/download/" + DECODED_FILENAME
)

# Códigos cortos aceptados para tipo_regimen, mapeados al valor decodificado
# tal como aparece en la columna TIPO_REGIMEN (ver 0.2-decode-data.ipynb).
TIPO_REGIMEN_MAP = {
    "i": "Importación",
    "e": "Exportación",
    "t": "Tránsito",
}

# Formatos de archivo aceptados para exportar el resultado de una consulta.
EXPORT_FORMATS = ("csv", "xlsx", "parquet")

# Matches any character that isn't a digit, to strip separators from an NCM code.
NCM_NON_DIGIT_PATTERN = re.compile(r"\D+")


def _normalize_ncm(code: str) -> str:
    """Strip separators from an NCM code or prefix.

    NCM values in the dataset are stored as plain digit strings (e.g.
    "7801100000"), but by HS convention people commonly write them with dots
    (e.g. "78.01" or "7801.10.00"). Stripping non-digit characters makes both
    forms match the same rows.

    Args:
        code: NCM code or prefix, with or without separators.

    Returns:
        The code with any non-digit characters removed.
    """
    return NCM_NON_DIGIT_PATTERN.sub("", code)


def _download_decoded_data(destination: Path) -> None:
    """Download the pre-built decoded dataset from the latest GitHub release.

    Downloads to a temporary file first and renames it into place only once
    complete, so an interrupted download never leaves a truncated file that
    looks like a valid cached dataset on the next run.

    Args:
        destination: Local path to save the downloaded parquet to.
    """
    logger.info("Dataset no encontrado localmente. Descargando desde %s...", RELEASE_DOWNLOAD_URL)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + ".tmp")

    response = requests.get(RELEASE_DOWNLOAD_URL, stream=True, timeout=30)
    response.raise_for_status()
    total = int(response.headers.get("content-length", 0))
    with (
        open(tmp_path, "wb") as file_,
        tqdm(total=total, unit="B", unit_scale=True, desc="Descargando dataset") as progress,
    ):
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            file_.write(chunk)
            progress.update(len(chunk))

    tmp_path.rename(destination)
    logger.info("Descarga completa: %s", destination)


def _decoded_data_path() -> Path:
    """Locate the decoded DUA parquet, downloading it first if it's missing.

    Returns:
        Path to data/processed/dua_<start>-<end>_decoded.parquet. If none is
        found locally, it's downloaded first from the latest GitHub release
        (see RELEASE_DOWNLOAD_URL).

    Raises:
        FileNotFoundError: If more than one local file matches the pattern
            (an ambiguous case that can't be resolved automatically).
    """
    data_processed = utils.data_processed_dir()
    candidates = [
        path for path in data_processed.glob("dua_*_decoded.parquet") if DECODED_PATTERN.match(path.name)
    ]
    if len(candidates) > 1:
        raise FileNotFoundError(
            f"Expected at most one dua_<start>-<end>_decoded.parquet file in {data_processed}, "
            f"found {candidates}."
        )
    if candidates:
        return candidates[0]

    destination = data_processed / DECODED_FILENAME
    _download_decoded_data(destination)
    return destination


def query_dua(
    years: int | Sequence[int],
    tipo_regimen: str | Sequence[str] | None = None,
    nombre: str | None = None,
    ncm: str | Sequence[str] | None = None,
) -> pl.DataFrame:
    """Consulta el dataset de DUA decodificado.

    A diferencia del dataset de importaciones de ARCA Comex, este incluye
    importaciones, exportaciones y tránsitos en la misma tabla, por lo que
    `tipo_regimen` permite acotar a uno o más de ellos.

    Args:
        years: Año o lista de años a incluir (filtra sobre ANIO_PRESENTACION).
        tipo_regimen: "i" (Importación), "e" (Exportación), "t" (Tránsito), o
            una lista de ellos (no distingue mayúsculas/minúsculas). `None`
            incluye los tres.
        nombre: Nombre (o parte del nombre) del importador/exportador a
            buscar. La búsqueda no distingue mayúsculas/minúsculas. Cuanto
            más específico, mejor: un término corto (ej. "sa") puede
            devolver miles de coincidencias distintas.
        ncm: Código NCM o lista de códigos/prefijos a buscar. Puede incluir
            puntos u otros separadores (ej. "78.01"); se ignoran.

    Returns:
        DataFrame de polars con las filas que cumplen los filtros.

    Raises:
        ValueError: Si no se especifica ni `nombre` ni `ncm`, o si
            `tipo_regimen` incluye un código fuera de TIPO_REGIMEN_MAP.
    """
    if nombre is None and ncm is None:
        raise ValueError("Debe indicar al menos `nombre` o `ncm`.")

    years_list = [years] if isinstance(years, int) else list(years)
    filters = [pl.col("ANIO_PRESENTACION").is_in(years_list)]

    if tipo_regimen is not None:
        tipo_regimen_list = [tipo_regimen] if isinstance(tipo_regimen, str) else list(tipo_regimen)
        codes = [code.lower() for code in tipo_regimen_list]
        invalid = set(codes) - set(TIPO_REGIMEN_MAP)
        if invalid:
            valid = ", ".join(f"{code} ({label})" for code, label in TIPO_REGIMEN_MAP.items())
            raise ValueError(f"tipo_regimen inválido: {sorted(invalid)}. Valores válidos: {valid}.")
        filters.append(pl.col("TIPO_REGIMEN").is_in([TIPO_REGIMEN_MAP[code] for code in codes]))

    if nombre is not None:
        filters.append(pl.col("NOMBRE_IMPORTADOR_EXPORTADOR").str.contains(f"(?i){nombre}"))

    if ncm is not None:
        ncm_list = [_normalize_ncm(code) for code in ([ncm] if isinstance(ncm, str) else ncm)]
        ncm_filter = pl.col("NCM").str.starts_with(ncm_list[0])
        for code in ncm_list[1:]:
            ncm_filter = ncm_filter | pl.col("NCM").str.starts_with(code)
        filters.append(ncm_filter)

    combined_filter = filters[0]
    for extra_filter in filters[1:]:
        combined_filter = combined_filter & extra_filter

    return pl.scan_parquet(_decoded_data_path()).filter(combined_filter).collect()


def export_query_result(
    df_result: pl.DataFrame,
    query_years: int | Sequence[int],
    query_tipo_regimen: str | Sequence[str] | None,
    query_nombre: str | None,
    query_ncm: str | Sequence[str] | None,
    output_dir: Path | None = None,
    formato: str = "csv",
) -> Path | None:
    """Exporta el resultado de una consulta a un archivo.

    El nombre del archivo se genera dinámicamente a partir de los parámetros
    de la consulta (régimen, nombre, NCM y rango de años).

    Args:
        df_result: DataFrame a exportar.
        query_years: Año o lista de años usados en la consulta.
        query_tipo_regimen: Código(s) de régimen usados en la consulta
            (i/e/t, o None).
        query_nombre: Nombre usado en la consulta (o None).
        query_ncm: Código(s) NCM usados en la consulta (o None).
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
        raise ValueError(f"formato inválido: {formato!r}. Valores válidos: {EXPORT_FORMATS}.")

    if df_result.height == 0:
        logger.info("La consulta no devolvió filas. No se generó ningún archivo.")
        return None

    years_list = [query_years] if isinstance(query_years, int) else list(query_years)
    start_year, end_year = min(years_list), max(years_list)
    year_suffix = f"{start_year}-{end_year}" if start_year != end_year else str(start_year)

    name_parts = []
    if query_tipo_regimen:
        if isinstance(query_tipo_regimen, str):
            name_parts.append(TIPO_REGIMEN_MAP.get(query_tipo_regimen.lower(), query_tipo_regimen).lower())
        else:
            labels = [TIPO_REGIMEN_MAP.get(regimen.lower(), regimen) for regimen in query_tipo_regimen]
            name_parts.append("-".join(label.lower() for label in labels))
    if query_nombre:
        name_parts.append(query_nombre.strip().replace(" ", "_").lower())
    if query_ncm:
        if isinstance(query_ncm, str):
            name_parts.append(_normalize_ncm(query_ncm))
        else:
            name_parts.append("-".join(_normalize_ncm(code) for code in query_ncm))

    prefix = "_".join(name_parts)
    export_dir = output_dir if output_dir is not None else Path.cwd()
    if not export_dir.exists():
        logger.info("El directorio de salida no existe, se crea: %s", export_dir)
        export_dir.mkdir(parents=True)
    export_path = export_dir / f"{prefix}_{year_suffix}.{formato}"

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
    """Construye el parser de argumentos de la CLI de consulta.

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
            "--nombre y/o --ncm."
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
        "-nom",
        "--nombre",
        type=str,
        default=None,
        help=(
            "Nombre (o parte del nombre) del importador/exportador a buscar "
            "(no distingue mayúsculas/minúsculas). Cuanto más específico el "
            'nombre, mejor: un término corto como "sa" puede devolver miles '
            "de coincidencias distintas."
        ),
    )
    parser.add_argument(
        "-n",
        "--ncm",
        type=str,
        nargs="+",
        default=None,
        metavar="NCM",
        help=(
            "Uno o más códigos NCM (o prefijos) a buscar, separados por espacios "
            "(ej. --ncm 73 84.20). Los puntos son opcionales (78.01 y 7801 son "
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
    """Punto de entrada de la CLI de consulta.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si la consulta se ejecutó
        correctamente, 1 si faltaron argumentos requeridos.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.nombre is None and args.ncm is None:
        parser.error("Debe indicar al menos --nombre o --ncm.")

    df_result = query_dua(
        years=args.years, tipo_regimen=args.tipo_regimen, nombre=args.nombre, ncm=args.ncm
    )
    export_query_result(
        df_result,
        args.years,
        args.tipo_regimen,
        args.nombre,
        args.ncm,
        output_dir=args.output,
        formato=args.formato,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
