"""Pipeline de DUAs: descarga por FTP, conversión, historial, tabla final y decodificación.

Lo usan tanto los notebooks `0.0`-`0.2` (para armar el dataset en local) como
`python -m uruguay_dua_comex.update` (para incorporar los meses nuevos o
modificados desde GitHub Actions).

Los pasos son:

1. Descarga (`download_month`): cada archivo mensual `dmYYYYMM.zip` del FTP
   público de la DNA (ver `docs/configuracion-cliente-ftp.pdf`). Solo se
   descargan meses ya cerrados: el del mes en curso se reescribe a diario.
2. Conversión (`convert_month_to_parquet`): los tres XML de cada zip (Ing, Mod,
   Anu) a parquet, en `data/interim/`.
3. Historial (`build_history`): todas las filas de todos los Ing/Mod/Anu en un
   solo archivo. Es lo único que hace falta para reconstruir la tabla final,
   así que una actualización solo convierte los meses nuevos o modificados.
4. Tabla final (`build_final_tables`): la versión más reciente de cada
   declaración, más la lista de anulados (ver notebook 0.1).
5. Decodificación (`decode_dataset`): traduce los códigos verificados y
   renombra las columnas (ver notebook 0.2).
"""

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from ftplib import FTP, error_perm
from pathlib import Path

import polars as pl

from uruguay_dua_comex import utils
from uruguay_dua_comex.query import DECODED_FILENAME

logger = logging.getLogger(__name__)

# Servidor FTP público de la DNA (acceso anónimo, puerto 21). Los DUA están en
# una carpeta por año, con archivos diarios (dd) y mensuales (dm).
FTP_HOST = "ftp.aduanas.gub.uy"
FTP_DUA_DIR = "/DUA Diarios XML"

# Primer mes publicado (Ley 19.438, art. 43, de 2016).
FIRST_PERIOD = 201601

# Hora de Uruguay (UTC-3, sin horario de verano), para saber qué mes está cerrado.
URUGUAY_TZ = timezone(timedelta(hours=-3))

# Pausa entre pedidos al FTP, para no sobrecargar el servidor.
FTP_DELAY_SECONDS = 0.2

HISTORY_FILENAME = "dua_historial.parquet"
ITEMS_FILENAME = "dua.parquet"
CANCELLED_FILENAME = "dua_anulados.parquet"

# Monthly archives: DMyyyymm.zip (older years) or dmyyyymm.zip (newer years).
# When DNA republishes a month, the new version is saved next to the old one
# as dmyyyymm_<server timestamp>.zip, since data/raw/ is never overwritten.
# Daily archives (ddyyyymmdd.zip) are ignored: see notebook 0.1.
MONTHLY_ZIP_PATTERN = re.compile(r"^dm(\d{6})(?:_\d{14})?\.zip$", re.IGNORECASE)

# The three XML files inside each zip, e.g. DMIng201601.xml / dmmod202306.xml.
MEMBER_PATTERN = re.compile(r"^d[dm](ing|mod|anu)\d+\.xml$", re.IGNORECASE)

# Order in which the spec says the files of the same month must be applied.
KIND_ORDER = {"ing": 0, "mod": 1, "anu": 2}

# A declaration is identified by its year plus its public number.
DUA_KEY = ["DDANO_PRESE", "DDNUME_CORRE_PUBLICO"]

# Columns added to every row to record which file it came from.
SOURCE_COLUMNS = ["FUENTE_PERIODO", "FUENTE_TIPO"]

# Columns kept from the Ing/Mod files, in the order the spec lists them, with
# the type each one is stored as. Codes stay as text to keep leading zeros.
ITEM_COLUMNS = {
    "DDANO_PRESE": pl.Int16,  # Año
    "DDNUME_CORRE_PUBLICO": pl.String,  # Número público del DUA
    "DDFECH_INGSI": pl.Date,  # Fecha del DUA
    "DDTIPO_REGI": pl.String,  # Tipo de régimen: I / E / T
    "DDPAIS_ORIGE": pl.String,  # País de origen
    "DDPART_NANDI": pl.String,  # Nomenclatura Común del Mercosur (NCM)
    "DDPUER_EMBAR": pl.String,  # País de procedencia (impo) / destino (expo)
    "DDCONV_INTER": pl.String,  # Convenio internacional
    "DDCODI_LIBER": pl.String,  # Exoneración
    "DDQUNICOM": pl.Float64,  # Cantidad de unidades comerciales
    "DDTUNICOM": pl.String,  # Tipo de unidades comerciales
    "DDUNID_FIQTY": pl.Float64,  # Cantidad de unidades físicas
    "DDUNID_FIDES": pl.String,  # Tipo de unidades físicas
    "DDVAD_INCR": pl.Float64,  # Valor en aduana
    "DDIMA_DOLAR": pl.Float64,  # IMADUNI U$S
    "DDLIMA_DOLAR": pl.Float64,  # IMADUNI U$S liberado
    "DDRMI_DOLAR": pl.Float64,  # Recargo mínimo U$S
    "DDLRMI_DOLAR": pl.Float64,  # Recargo mínimo U$S liberado
    "DDRAD_DOLAR": pl.Float64,  # Recargo adicional U$S
    "DDLRAD_DOLAR": pl.Float64,  # Recargo adicional U$S liberado
    "DDRMO_DOLAR": pl.Float64,  # Recargo móvil U$S
    "DDLRMO_DOLAR": pl.Float64,  # Recargo móvil U$S liberado
    "DDIVA_DOLAR": pl.Float64,  # IVA U$S
    "DDLIVA_DOLAR": pl.Float64,  # IVA U$S liberado
    "DDLIVAA_DOLA": pl.Float64,  # IVA anticipo U$S liberado
    "DDIVAA_DOLAR": pl.Float64,  # IVA anticipo U$S
    "DDPOR_IMADUN": pl.Float64,  # Porcentaje IMADUNI
    "DDPOR_RMI": pl.Float64,  # Porcentaje recargo mínimo
    "DDPOR_RAD": pl.Float64,  # Porcentaje recargo adicional
    "DDPOR_IVA": pl.Float64,  # Porcentaje IVA
    "DDPOR_IVAA": pl.Float64,  # Porcentaje IVA anticipo
    "DDVIA_TRANSP": pl.String,  # Vía de transporte
    "DDUNID_TRANS": pl.String,  # Not in the spec; only published until 2019
    "DDADUAINGEGR": pl.String,  # Aduana de ingreso/egreso
    "DDTIPO_DOCUM": pl.String,  # Tipo de documento del importador/exportador
    "DDLIBR_TRIBU": pl.String,  # Documento del importador/exportador
    "DDPESO_BRUTO": pl.Float64,  # Peso bruto
    "DDPESO_NETO": pl.Float64,  # Peso neto
    "DDDNOMBRE": pl.String,  # Importador/exportador
    "DDCODI_REGI": pl.String,  # Régimen; only published from 2020
    "DDTIPO_OPERA": pl.String,  # Subrégimen; only published from 2020
}

# Anu files only list which declarations were cancelled. The year tag has a
# different name there (DFANOPRE); it is renamed to match the Ing/Mod files.
ANU_COLUMNS = {
    "DFANOPRE": "DDANO_PRESE",
    "DDNUME_CORRE_PUBLICO": "DDNUME_CORRE_PUBLICO",
}

# Official code catalogs (see notebook 0.2 for the sources and for why every
# other coded column is left as DNA's raw code instead of guessed at).
# DDTIPO_REGI: "Tipo Régimen (Importación/Exportación)" in
# docs/FormatoDUADiariosPublicos.htm; T (Tránsito) is the only other code.
TIPO_REGI = {"I": "Importación", "E": "Exportación", "T": "Tránsito"}

# DDTIPO_DOCUM: verbatim from DNA's "DUA de Importación" and "Instructivo de
# llenado del DUA para Exportación" field specs.
TIPO_DOCUM = {
    "2": "Cédula de identidad de la R.O.U.",
    "4": "R.U.T.",
    "6": "Pasaporte, para extranjeros",
}

# DDADUAINGEGR: partial -- only these three offices are named in DNA's PDFs.
ADUANAS = {
    "001": "Montevideo",
    "002": "Carrasco",
    "009": "Aceguá",
}

# Codes are decoded in place, under their raw DD* name, before the rename.
DECODED_COLUMNS = {
    "DDTIPO_REGI": TIPO_REGI,
    "DDTIPO_DOCUM": TIPO_DOCUM,
    "DDADUAINGEGR": ADUANAS,
}

# Intuitive names for DNA's raw DD* tags (see notebook 0.2). DDUNID_TRANS is
# deliberately left out: its meaning isn't documented anywhere found.
RENAME_COLUMNS = {
    "DDANO_PRESE": "ANIO_PRESENTACION",
    "DDNUME_CORRE_PUBLICO": "NUMERO_PUBLICO_DUA",
    "DDFECH_INGSI": "FECHA_DUA",
    "DDTIPO_REGI": "TIPO_REGIMEN",
    "DDPAIS_ORIGE": "PAIS_ORIGEN",
    "DDPART_NANDI": "NCM",
    "DDPUER_EMBAR": "PAIS_PROCEDENCIA_DESTINO",
    "DDCONV_INTER": "CONVENIO_INTERNACIONAL",
    "DDCODI_LIBER": "CODIGO_EXONERACION",
    "DDQUNICOM": "CANTIDAD_UNIDADES_COMERCIALES",
    "DDTUNICOM": "TIPO_UNIDAD_COMERCIAL",
    "DDUNID_FIQTY": "CANTIDAD_UNIDADES_FISICAS",
    "DDUNID_FIDES": "TIPO_UNIDAD_FISICA",
    "DDVAD_INCR": "VALOR_ADUANA",
    "DDIMA_DOLAR": "IMADUNI_USD",
    "DDLIMA_DOLAR": "IMADUNI_LIBERADO_USD",
    "DDRMI_DOLAR": "RECARGO_MINIMO_USD",
    "DDLRMI_DOLAR": "RECARGO_MINIMO_LIBERADO_USD",
    "DDRAD_DOLAR": "RECARGO_ADICIONAL_USD",
    "DDLRAD_DOLAR": "RECARGO_ADICIONAL_LIBERADO_USD",
    "DDRMO_DOLAR": "RECARGO_MOVIL_USD",
    "DDLRMO_DOLAR": "RECARGO_MOVIL_LIBERADO_USD",
    "DDIVA_DOLAR": "IVA_USD",
    "DDLIVA_DOLAR": "IVA_LIBERADO_USD",
    "DDLIVAA_DOLA": "IVA_ANTICIPO_LIBERADO_USD",
    "DDIVAA_DOLAR": "IVA_ANTICIPO_USD",
    "DDPOR_IMADUN": "IMADUNI_PORCENTAJE",
    "DDPOR_RMI": "RECARGO_MINIMO_PORCENTAJE",
    "DDPOR_RAD": "RECARGO_ADICIONAL_PORCENTAJE",
    "DDPOR_IVA": "IVA_PORCENTAJE",
    "DDPOR_IVAA": "IVA_ANTICIPO_PORCENTAJE",
    "DDVIA_TRANSP": "VIA_TRANSPORTE",
    "DDADUAINGEGR": "ADUANA_INGRESO_EGRESO",
    "DDTIPO_DOCUM": "TIPO_DOCUMENTO_IMPOEXPO",
    "DDLIBR_TRIBU": "NUMERO_DOCUMENTO_IMPOEXPO",
    "DDPESO_BRUTO": "PESO_BRUTO",
    "DDPESO_NETO": "PESO_NETO",
    "DDDNOMBRE": "NOMBRE_IMPORTADOR_EXPORTADOR",
    "DDCODI_REGI": "REGIMEN_ADUANERO",
    "DDTIPO_OPERA": "SUBREGIMEN",
}


def _ftp_path(period: int) -> str:
    """Path of a month's file on the server (which ignores letter case).

    Args:
        period: Month, as yyyymm.

    Returns:
        e.g. "/DUA Diarios XML/2026/dm202609.zip".
    """
    return f"{FTP_DUA_DIR}/{str(period)[:4]}/dm{period}.zip"


@dataclass
class RemoteMonth:
    """Un archivo mensual publicado en el FTP de la DNA.

    Attributes:
        period: Mes del archivo, como yyyymm.
        size: Tamaño en bytes, según el servidor.
        modified: Última modificación, según el servidor (UTC).
    """

    period: int
    size: int
    modified: datetime

    @property
    def version(self) -> str:
        """Fecha de modificación como yyyymmddhhmmss, para identificar la versión."""
        return self.modified.strftime("%Y%m%d%H%M%S")


def connect() -> FTP:
    """Open an anonymous session on DNA's FTP server.

    Returns:
        A logged-in FTP connection.
    """
    ftp = FTP(FTP_HOST, timeout=120)
    ftp.login()
    return ftp


def last_finalized_period() -> int:
    """Return the last month that has ended, in Uruguay time.

    Returns:
        The previous month, as yyyymm. The current month's file is rewritten
        daily until the month ends, so it's never treated as final.
    """
    first_of_month = datetime.now(URUGUAY_TZ).replace(day=1)
    previous = first_of_month - timedelta(days=1)
    return previous.year * 100 + previous.month


def _periods(first: int, last: int) -> list[int]:
    """List every month from first to last, inclusive.

    Args:
        first: First month, as yyyymm.
        last: Last month, as yyyymm.

    Returns:
        The months in order, as yyyymm.
    """
    periods = []
    year, month = divmod(first, 100)
    while year * 100 + month <= last:
        periods.append(year * 100 + month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return periods


def list_remote_months(ftp: FTP) -> list[RemoteMonth]:
    """Get the size and modification time of every finalized monthly file.

    The server blocks directory listings from many networks, so each file is
    queried by name with SIZE and MDTM, which only use the control connection.

    Args:
        ftp: Open connection from `connect`.

    Returns:
        One RemoteMonth per published month, from FIRST_PERIOD to the last
        finalized month.
    """
    remote_months = []
    for period in _periods(FIRST_PERIOD, last_finalized_period()):
        path = _ftp_path(period)
        try:
            size = int(ftp.sendcmd(f"SIZE {path}").split()[1])
            # MDTM answers "213 yyyymmddhhmmss", in UTC.
            modified = datetime.strptime(
                ftp.sendcmd(f"MDTM {path}").split()[1][:14], "%Y%m%d%H%M%S"
            ).replace(tzinfo=UTC)
        except error_perm:
            logger.warning("%s no está publicado en el FTP.", path)
            continue
        remote_months.append(RemoteMonth(period, size, modified))
        time.sleep(FTP_DELAY_SECONDS)
    return remote_months


def local_monthly_zips() -> dict[int, Path]:
    """Find the newest local version of every monthly zip under data/raw/.

    Returns:
        Mapping of period (yyyymm) to its newest zip (by modification time,
        which is set to the server's), sorted by period.
    """
    zips: dict[int, Path] = {}
    for path in utils.data_raw_dir().rglob("*.zip"):
        match = MONTHLY_ZIP_PATTERN.match(path.name)
        if match is None:
            continue
        period = int(match.group(1))
        if period not in zips or path.stat().st_mtime > zips[period].stat().st_mtime:
            zips[period] = path
    return dict(sorted(zips.items()))


def _is_same_version(path: Path, remote: RemoteMonth) -> bool:
    """Tell whether a local zip is the same version as the one on the server.

    Args:
        path: Local zip.
        remote: Server file to compare against.

    Returns:
        True if both have the same size and modification time. Times are
        compared to the minute, since some FTP clients (e.g. WinSCP) keep the
        server's time without seconds.
    """
    stat = path.stat()
    return (
        stat.st_size == remote.size
        and abs(stat.st_mtime - remote.modified.timestamp()) < 60
    )


def download_month(ftp: FTP, remote: RemoteMonth) -> Path:
    """Download one monthly zip into data/raw/<year>/, unless it's already there.

    data/raw/ is never overwritten: if an older version of the month exists,
    the new one is saved next to it as dm<yyyymm>_<server timestamp>.zip. The
    file's modification time is set to the server's, so later runs can tell
    whether the local copy is current.

    Args:
        ftp: Open connection from `connect`.
        remote: Month to download, from `list_remote_months`.

    Returns:
        Path to the local zip.
    """
    existing = local_monthly_zips().get(remote.period)
    if existing is not None and _is_same_version(existing, remote):
        return existing

    year_dir = utils.data_raw_dir(str(remote.period)[:4])
    name = (
        f"dm{remote.period}.zip"
        if existing is None
        else f"dm{remote.period}_{remote.version}.zip"
    )
    zip_path = year_dir / name
    tmp_path = zip_path.with_name(f"{name}.tmp")

    logger.info(
        "Descargando %s (%.1f MB)...", _ftp_path(remote.period), remote.size / 1e6
    )
    year_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tmp_path.open("wb") as file_:
            ftp.retrbinary(f"RETR {_ftp_path(remote.period)}", file_.write)
        tmp_path.replace(zip_path)
    finally:
        # Only left behind if the download failed; never leave it in data/raw/.
        tmp_path.unlink(missing_ok=True)
    timestamp = remote.modified.timestamp()
    os.utime(zip_path, (timestamp, timestamp))
    time.sleep(FTP_DELAY_SECONDS)
    return zip_path


def _read_xml_rows(
    zf: zipfile.ZipFile, member: str, columns: list[str]
) -> pl.DataFrame:
    """Read the rows of one XML file inside a zip into a table of raw strings.

    Rows are read one at a time and discarded right after, so memory stays low
    even for the largest files. Tags missing from a row (newer files leave out
    empty fields) become null.

    Args:
        zf: Open zip archive.
        member: Name of the XML file inside the archive.
        columns: Tags to keep; every other tag is ignored.

    Returns:
        One row per XML row, every column as a string.
    """
    data: dict[str, list[str | None]] = {column: [] for column in columns}
    with zf.open(member) as xml_file:
        for _, element in ET.iterparse(xml_file):
            # Ing/Mod rows are <ROW_DUASDIA>, Anu rows are <ROW>.
            if element.tag not in ("ROW_DUASDIA", "ROW"):
                continue
            values = {child.tag: child.text for child in element}
            for column in columns:
                data[column].append(values.get(column))
            element.clear()
    return pl.DataFrame(data, schema={column: pl.String for column in columns})


def _blank_to_null(df: pl.DataFrame) -> pl.DataFrame:
    """Strip the padding spaces from every value and turn empty values into null.

    Args:
        df: Table of raw strings.

    Returns:
        The same table, stripped, with empty strings as null.
    """
    return df.with_columns(pl.all().str.strip_chars().replace("", None))


def _clean_items(df: pl.DataFrame) -> pl.DataFrame:
    """Cast an Ing/Mod table from raw strings to its final column types.

    Casts are strict, so an unexpected value (e.g. text in an amount column)
    stops the run instead of silently becoming null.

    Args:
        df: Ing/Mod table from `_read_xml_rows`.

    Returns:
        The table with the types in ITEM_COLUMNS.
    """
    df = _blank_to_null(df)
    casts = []
    for column, dtype in ITEM_COLUMNS.items():
        if dtype == pl.Date:
            casts.append(pl.col(column).str.to_date("%Y-%m-%d"))
        elif dtype != pl.String:
            casts.append(pl.col(column).cast(dtype, strict=True))
    # Older files drop the leading zeros of the country of origin ("76" instead
    # of "076"); put them back so the codes match across years.
    casts.append(pl.col("DDPAIS_ORIGE").str.zfill(3))
    return df.with_columns(casts)


def monthly_parquet_paths(period: int) -> dict[str, Path]:
    """Where the three converted files of one month are stored.

    Args:
        period: Month, as yyyymm.

    Returns:
        Mapping of file kind ("ing", "mod", "anu") to its parquet path under
        data/interim/<year>/<yyyymm>/.
    """
    month_dir = utils.data_interim_dir(str(period)[:4], str(period))
    return {kind: month_dir / f"{kind}_{period}.parquet" for kind in KIND_ORDER}


def convert_month_to_parquet(period: int, zip_path: Path) -> dict[str, Path]:
    """Convert one monthly zip into three parquet files (ing, mod and anu).

    A month already converted is skipped, unless its zip is newer than the
    converted files (a new version downloaded from the server).

    Args:
        period: Month of the zip, as yyyymm.
        zip_path: Path to the monthly zip archive.

    Returns:
        Mapping of file kind ("ing", "mod", "anu") to its parquet path.

    Raises:
        ValueError: If the zip is missing any of its three XML files.
    """
    output_paths = monthly_parquet_paths(period)

    zip_mtime = zip_path.stat().st_mtime
    if all(
        p.exists() and p.stat().st_mtime >= zip_mtime for p in output_paths.values()
    ):
        return output_paths

    with zipfile.ZipFile(zip_path) as zf:
        members = {}
        for name in zf.namelist():
            match = MEMBER_PATTERN.match(Path(name).name)
            if match:
                members[match.group(1).lower()] = name
        missing = set(KIND_ORDER) - set(members)
        if missing:
            raise ValueError(
                f"{zip_path.name} is missing its {sorted(missing)} file(s)."
            )

        # Every row records which file it came from; build_final_tables uses
        # this to know which version of a declaration is the most recent.
        source_period = pl.lit(period, dtype=pl.Int32).alias("FUENTE_PERIODO")

        tables = {}
        for kind in ("ing", "mod"):
            df_items = _clean_items(
                _read_xml_rows(zf, members[kind], list(ITEM_COLUMNS))
            )
            tables[kind] = df_items.with_columns(
                source_period, pl.lit(kind).alias("FUENTE_TIPO")
            )

        df_cancelled = _read_xml_rows(zf, members["anu"], list(ANU_COLUMNS)).rename(
            ANU_COLUMNS
        )
        df_cancelled = _blank_to_null(df_cancelled).with_columns(
            pl.col("DDANO_PRESE").cast(pl.Int16, strict=True)
        )
        tables["anu"] = df_cancelled.with_columns(
            source_period, pl.lit("anu").alias("FUENTE_TIPO")
        )

    output_paths["ing"].parent.mkdir(parents=True, exist_ok=True)
    for kind, table in tables.items():
        table.write_parquet(output_paths[kind])
    return output_paths


def build_history(converted: dict[int, dict[str, Path]], extend_existing: bool) -> None:
    """Write every Ing/Mod/Anu row of the given months to the history file.

    The history holds every appearance of every declaration, so the final
    table can be rebuilt from it without converting the XML files again. Anu
    rows only fill the declaration key and source columns.

    Args:
        converted: Mapping of period (yyyymm) to that month's parquet paths,
            from `convert_month_to_parquet`.
        extend_existing: If True, add the months to the existing history,
            dropping its rows for those months first, so a republished month
            replaces its previous version. If False, build the history from
            `converted` only.
    """
    history_path = utils.data_processed_dir(HISTORY_FILENAME)
    frames = [
        pl.scan_parquet(paths[kind])
        for paths in converted.values()
        for kind in KIND_ORDER
    ]
    if extend_existing:
        frames.insert(
            0,
            pl.scan_parquet(history_path).filter(
                ~pl.col("FUENTE_PERIODO").is_in(list(converted))
            ),
        )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = history_path.with_name(f"{history_path.name}.tmp")
    (
        pl.concat(frames, how="diagonal_relaxed")
        .select(*ITEM_COLUMNS, *SOURCE_COLUMNS)
        .sink_parquet(tmp_path)
    )
    tmp_path.replace(history_path)


def _event_order() -> pl.Expr:
    """Sort number of an appearance: month * 10 + position of its file kind (Ing, Mod, Anu).

    Returns:
        Expression computing the sort number from FUENTE_PERIODO and FUENTE_TIPO.
    """
    kind_position = pl.col("FUENTE_TIPO").replace_strict(
        KIND_ORDER, return_dtype=pl.Int64
    )
    return pl.col("FUENTE_PERIODO").cast(pl.Int64) * 10 + kind_position


def build_final_tables() -> None:
    """Build the table of valid declarations and the list of cancellations from the history.

    For each declaration (year + number), only the items from its most recent
    appearance are kept. If that appearance is a cancellation, there are no
    items to keep, so the declaration drops out on its own. See notebook 0.1.
    """
    history = pl.scan_parquet(utils.data_processed_dir(HISTORY_FILENAME))
    items = history.filter(pl.col("FUENTE_TIPO") != "anu")
    cancelled = history.filter(pl.col("FUENTE_TIPO") == "anu")

    # For each declaration, the sort number of its most recent appearance in
    # any Ing, Mod or Anu file.
    latest_appearance = (
        history.select(*DUA_KEY, _event_order().alias("ORDEN"))
        .group_by(DUA_KEY)
        .agg(pl.col("ORDEN").max().alias("ORDEN_ULTIMO"))
    )

    # Keep only the items that belong to that most recent appearance. When the
    # most recent appearance is a cancellation, no item matches it, so the
    # cancelled declaration disappears from the table.
    final_items = (
        items.with_columns(_event_order().alias("ORDEN"))
        .join(latest_appearance, on=DUA_KEY, how="inner")
        .filter(pl.col("ORDEN") == pl.col("ORDEN_ULTIMO"))
        .drop("ORDEN", "ORDEN_ULTIMO")
    )

    items_path = utils.data_processed_dir(ITEMS_FILENAME)
    logger.info("Escribiendo %s...", items_path)
    final_items.sink_parquet(items_path)

    cancelled_path = utils.data_processed_dir(CANCELLED_FILENAME)
    logger.info("Escribiendo %s...", cancelled_path)
    (
        cancelled.select(*DUA_KEY, pl.col("FUENTE_PERIODO").alias("PERIODO_ANULACION"))
        .unique()
        .sort("PERIODO_ANULACION", *DUA_KEY)
        .sink_parquet(cancelled_path)
    )

    # Quick summary so each run can be sanity-checked at a glance.
    df_summary = (
        pl.scan_parquet(items_path)
        .select(
            pl.len().alias("items"), pl.struct(DUA_KEY).n_unique().alias("declarations")
        )
        .collect()
    )
    removed = cancelled.select(pl.struct(DUA_KEY).n_unique()).collect().item()
    logger.info(
        "%s ítems de %s declaraciones válidas; %s declaraciones anuladas, listadas aparte.",
        f"{df_summary['items'][0]:,}",
        f"{df_summary['declarations'][0]:,}",
        f"{removed:,}",
    )


def decode_dataset() -> None:
    """Decode the verified codes and rename the columns of the final table.

    Reads data/processed/dua.parquet and writes data/processed/dua_decoded.parquet.
    A code with no catalog match passes through unchanged rather than becoming
    a wrong description or null. See notebook 0.2.
    """
    lf = pl.scan_parquet(utils.data_processed_dir(ITEMS_FILENAME))

    # Coverage has to be measured against the raw codes before overwriting
    # them: once decoded in place, an unmatched raw code looks the same as
    # before. A null code counts as undecoded too.
    df_coverage = lf.select(
        [
            (~pl.col(column).is_in(list(catalog)))
            .fill_null(True)
            .sum()
            .alias(f"{column}_sin_decodificar")
            for column, catalog in DECODED_COLUMNS.items()
        ]
        + [pl.len().alias("total_filas")]
    ).collect()
    logger.info(df_coverage)

    for column, catalog in DECODED_COLUMNS.items():
        lf = lf.with_columns(pl.col(column).replace(catalog))
    lf = lf.rename(RENAME_COLUMNS)

    decoded_path = utils.data_processed_dir(DECODED_FILENAME)
    logger.info("Escribiendo %s...", decoded_path)
    tmp_path = decoded_path.with_name(f"{decoded_path.name}.tmp")
    lf.sink_parquet(tmp_path)
    tmp_path.replace(decoded_path)
