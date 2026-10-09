"""Actualización del dataset con los meses nuevos o modificados en el FTP de la DNA.

Se corre con `python -m uruguay_dua_comex.update`, pensado para GitHub Actions
(ver `.github/workflows/update-data.yml`), aunque también funciona en local.
Compara el tamaño y la fecha de cada archivo mensual cerrado del FTP con los ya
procesados en `data/manifest.json`, y solo descarga y convierte los que
cambiaron. Después reconstruye la tabla final desde el historial (ver
`pipeline.build_history`), porque las modificaciones y anulaciones de un mes
pueden afectar declaraciones de meses anteriores.

Publicar el release y commitear el manifest quedan a cargo del workflow; este
módulo le informa qué cambió a través de `GITHUB_OUTPUT` cuando corre en Actions.
"""

import argparse
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from uruguay_dua_comex import utils
from uruguay_dua_comex.pipeline import (
    HISTORY_FILENAME,
    URUGUAY_TZ,
    RemoteMonth,
    build_final_tables,
    build_history,
    connect,
    convert_month_to_parquet,
    decode_dataset,
    download_month,
    list_remote_months,
)
from uruguay_dua_comex.query import download_release_asset

logger = logging.getLogger(__name__)

MANIFEST_PATH = utils.data_dir("manifest.json")


@dataclass
class MonthRecord:
    """Registro de un mes ya procesado, tal como se guarda en el manifest.

    Attributes:
        size: Tamaño del archivo mensual en el FTP, en bytes.
        modified: Fecha de modificación en el FTP (UTC), como yyyymmddhhmmss.
        processed_at: Fecha de procesamiento, en formato ISO (AAAA-MM-DD).
    """

    size: int
    modified: str
    processed_at: str

    def matches(self, remote: RemoteMonth) -> bool:
        """Tell whether this record is the same version as the file on the server.

        Args:
            remote: File on the server, from `list_remote_months`.

        Returns:
            True if size and modification time are the same.
        """
        return self.size == remote.size and self.modified == remote.version


def load_manifest() -> dict[str, MonthRecord]:
    """Read the processed months from data/manifest.json.

    Returns:
        Mapping of yyyymm -> MonthRecord, empty if the manifest doesn't exist.
    """
    if not MANIFEST_PATH.exists():
        return {}
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {period: MonthRecord(**record) for period, record in raw.items()}


def save_manifest(manifest: dict[str, MonthRecord]) -> None:
    """Write the processed months to data/manifest.json, sorted by month.

    Args:
        manifest: Mapping of yyyymm -> MonthRecord.
    """
    raw = {period: asdict(manifest[period]) for period in sorted(manifest)}
    MANIFEST_PATH.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def _format_period(period: int | str) -> str:
    """Format yyyymm as yyyy-mm for logs and release notes.

    Args:
        period: Month as yyyymm.

    Returns:
        Month as yyyy-mm.
    """
    text = str(period)
    return f"{text[:4]}-{text[4:]}"


def _write_github_outputs(outputs: dict[str, str]) -> None:
    """Pass values to later workflow steps when running in GitHub Actions.

    Args:
        outputs: Output name -> value. Ignored outside GitHub Actions.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file is None:
        return
    with Path(output_file).open("a", encoding="utf-8") as file_:
        file_.writelines(f"{name}={value}\n" for name, value in outputs.items())


def update() -> list[int]:
    """Process every finalized month that is new or changed on the FTP server.

    Changed months are downloaded and converted one at a time, replaced in the
    history (downloaded first from the latest release if it isn't local), and
    the final and decoded tables are rebuilt from it. The manifest is saved
    only after every table is written.

    Returns:
        The yyyymm months processed, sorted; empty if nothing changed.
    """
    manifest = load_manifest()
    ftp = connect()
    remote_months = list_remote_months(ftp)
    changed = [
        remote
        for remote in remote_months
        if str(remote.period) not in manifest
        or not manifest[str(remote.period)].matches(remote)
    ]
    logger.info(
        "Meses nuevos o modificados en el FTP: %s",
        [_format_period(remote.period) for remote in changed] or "ninguno",
    )
    if not changed:
        ftp.quit()
        return []

    converted = {}
    for remote in changed:
        zip_path = download_month(ftp, remote)
        logger.info("Convirtiendo %s...", _format_period(remote.period))
        converted[remote.period] = convert_month_to_parquet(remote.period, zip_path)
    ftp.quit()

    if not utils.data_processed_dir(HISTORY_FILENAME).exists():
        download_release_asset(HISTORY_FILENAME)
    build_history(converted, extend_existing=True)
    build_final_tables()
    decode_dataset()

    processed_at = datetime.now(URUGUAY_TZ).date().isoformat()
    for remote in changed:
        manifest[str(remote.period)] = MonthRecord(
            size=remote.size, modified=remote.version, processed_at=processed_at
        )
    save_manifest(manifest)
    return sorted(converted)


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de `python -m uruguay_dua_comex.update`.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si la actualización terminó bien.
    """
    parser = argparse.ArgumentParser(
        prog="uruguay-dua-update",
        description=(
            "Descarga del FTP de la DNA los meses cerrados nuevos o modificados "
            "desde la última actualización (según data/manifest.json), y "
            "reconstruye las tablas de data/processed/."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    processed = update()
    if not processed:
        logger.info("No hay meses nuevos ni modificados. El dataset ya está al día.")
        _write_github_outputs({"updated": "false"})
        return 0

    last_period = max(load_manifest())
    months = ", ".join(_format_period(period) for period in processed)
    logger.info(
        "Dataset actualizado hasta %s. Meses procesados: %s.",
        _format_period(last_period),
        months,
    )
    _write_github_outputs(
        {
            "updated": "true",
            "processed_months": months,
            "last_month": _format_period(last_period),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
