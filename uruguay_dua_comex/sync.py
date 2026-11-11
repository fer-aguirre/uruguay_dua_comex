"""Pone al día los datos locales con el release de GitHub.

Se corre con `uruguay-dua-sync` (o `python -m uruguay_dua_comex.sync` si
Windows bloquea el ejecutable). Para cada archivo del release que ya está en
`data/processed/`, compara la huella SHA-256 local con la que publica GitHub:

- si coinciden, el archivo está al día y no se toca;
- si no coinciden y el release es más nuevo que el archivo local, se descarga
  la versión del release;
- si no coinciden y el archivo local es más nuevo (por ejemplo, porque se armó
  en la computadora con código más nuevo), se avisa y se deja como está.

No descarga archivos que no estén en local (de eso se encargan las consultas)
ni hace `git pull`.

Este módulo tiene la misma estructura en argentina_afip_comex,
uruguay_dua_comex y colombia_dian_comex. Solo cambia lo propio de cada país:
el repositorio, el release y la función de descarga.
"""

import argparse
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from uruguay_dua_comex import utils
from uruguay_dua_comex.query import download_release_asset

logger = logging.getLogger(__name__)

# --- Propio de cada país ---
# Repositorio de GitHub y release (de la API de GitHub) con los datos.
REPOSITORY = "fer-aguirre/uruguay_dua_comex"
RELEASE = "latest"


def _download(filename: str) -> None:
    """Download one file of the release into data/processed/.

    Args:
        filename: Name of the file in the release.
    """
    download_release_asset(filename)


# --- Común a los tres proyectos ---
RELEASE_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/{RELEASE}"


@dataclass(frozen=True)
class ReleaseAsset:
    """A file of the GitHub release.

    Attributes:
        name: File name, the same as in data/processed/.
        sha256: SHA-256 published by GitHub, or None if it doesn't have one.
        updated_at: When the file was uploaded to the release (UTC).
    """

    name: str
    sha256: str | None
    updated_at: datetime


def fetch_release_assets() -> list[ReleaseAsset]:
    """List the files of the release, with their SHA-256 and upload date.

    Returns:
        One ReleaseAsset per file of the release.

    Raises:
        requests.HTTPError: If GitHub doesn't answer the request.
    """
    response = requests.get(
        RELEASE_API_URL,
        headers={"Accept": "application/vnd.github+json"},
        timeout=30,
    )
    response.raise_for_status()
    return [
        ReleaseAsset(
            name=asset["name"],
            # GitHub publishes it as "sha256:<hex>".
            sha256=asset["digest"].removeprefix("sha256:")
            if asset.get("digest")
            else None,
            updated_at=datetime.fromisoformat(asset["updated_at"]),
        )
        for asset in response.json()["assets"]
    ]


def file_sha256(path: Path) -> str:
    """Compute the SHA-256 of a local file.

    Args:
        path: File to hash.

    Returns:
        The hex digest, in the same format GitHub publishes.
    """
    with path.open("rb") as file_:
        return hashlib.file_digest(file_, "sha256").hexdigest()


def sync() -> None:
    """Update the local files that are behind the release.

    Only checks the release files already in data/processed/. Logs a
    summary: files up to date, updated, and kept because the local copy is
    newer than the release.
    """
    up_to_date, updated, kept = [], [], []
    for asset in fetch_release_assets():
        path = utils.data_processed_dir(asset.name)
        if not path.exists():
            continue
        if asset.sha256 is None:
            logger.warning("%s: el release no publica su huella; se omite.", asset.name)
            continue

        logger.info("Revisando %s...", asset.name)
        if file_sha256(path) == asset.sha256:
            up_to_date.append(asset.name)
            continue

        local_time = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if asset.updated_at > local_time:
            _download(asset.name)
            updated.append(asset.name)
        else:
            logger.warning(
                "%s: tu archivo es distinto y más nuevo que el del release "
                "(%s contra %s); se deja como está.",
                asset.name,
                local_time.astimezone().strftime("%Y-%m-%d %H:%M"),
                asset.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            )
            kept.append(asset.name)

    logger.info(
        "Listo: %d al día, %d actualizados, %d sin cambiar por ser más nuevos.",
        len(up_to_date),
        len(updated),
        len(kept),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de la CLI `uruguay-dua-sync`.

    Returns:
        Parser de argparse configurado.
    """
    parser = argparse.ArgumentParser(
        prog="uruguay-dua-sync",
        description=(
            "Compara los datos de data/processed/ con el release de GitHub y "
            "descarga los que estén desactualizados."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de `uruguay-dua-sync`.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si terminó bien.
    """
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
